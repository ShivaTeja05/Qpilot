"""Deciding a Run Gate card from the Controls section (a Studio session's mini file).

The tainted mini file has a no-template control that amplifies early on ``1-Mar``: leaving the
wells it taints out leaves no knock-out sample for the gene, so the gate's card is open and only
a person decides. Here the person does, over HTTP:

* leaving the wells out writes one ``curve.exclude_well`` per well to the session's inbox
  (proposed by Run Gate's rule, accepted by the person with the reason, one write), the study is
  analysed again without them (the ``analyse`` job), and the gate read at the new analysis says
  the wells are already left out, by whom and why;
* the new analysis is the one the gate measured: its numbers are the consequence test's;
* "Keep every well" puts them back (the first analysis again), and on a card with nothing to put
  back it records the keep (the rule's exclusions, rejected with the reason);
* an agent's request through MCP is ``pending_human`` and waits on the card; the person's click
  approves or turns it down;
* refusals: no reason, an unknown option or card, a stale view, a study analysed outside Studio.
"""

from __future__ import annotations

import pytest

from qpilot.core.proposals import verify_proposal_chain
from qpilot.mcp_server import QpilotTools
from qpilot.studio_service import EXCLUDE_KIND, GATE_MAKER, Studio
from qpilot.web.routers import gate as gate_router
from tests.web import test_gate_routes as routes
from tests.web.conftest import wait_job

# the tainted mini study and its gate, as the route tests build them (fixtures)
tainted_walked = routes.tainted_walked
tainted = routes.tainted
ready = routes.ready

REASON = "the NTC on this plate amplified within five cycles of the knock-outs"


@pytest.fixture(autouse=True)
def fresh_gate_cache():
    gate_router.clear()
    yield
    gate_router.clear()


def ntc_card(body: dict) -> dict:
    """The tainted NTC's consequence (it is the one card of the mini file)."""
    (c,) = (x for x in body["consequences"] if x["rule_id"] == "G-NTC-1")
    return c


def decide(c, study: str, card: str, option: str, reason: str = REASON, **extra):
    return c.post(
        f"/api/studies/{study}/gate/cards/{card}/decide",
        json={"option": option, "reason": reason, **extra},
    )


def studio_of(tainted) -> Studio:
    return tainted["ctx"].studio


def analysed(c, sid: str, answer: dict) -> str:
    """Wait for the analysis a decision started; the session's study id after it."""
    if answer.get("job"):
        job = wait_job(c, answer["job"])
        assert job["status"] == "done", job
    frame = c.get(f"/api/sessions/{sid}").json()
    assert frame["results_visible"]
    return frame["study_id"]


def test_the_view_says_a_person_decides_here(tainted):
    c, study = tainted["client"], tainted["study"]
    body = ready(c, study).json()
    assert body["can_decide"] and body["inbox_head"] == studio_of(tainted).head(tainted["sid"])
    assert "analyses the study again" in body["decide_note"]
    assert "Choose an option on a Decision Card" in body["how_to_apply"]
    conseq = ntc_card(body)
    assert conseq["can_decide"] and conseq["decision"] is None and conseq["requests"] == []
    assert conseq["decision_id"] == conseq["card_id"]
    (card,) = body["cards"]
    assert card["card"]["status"] == "open" and card["pending"] == []


def test_leaving_the_wells_out_is_recorded_and_analysed_again(tainted):
    c, study, sid, store = tainted["client"], tainted["study"], tainted["sid"], tainted["store"]
    body = ready(c, study).json()
    conseq = ntc_card(body)
    (option,) = conseq["options"]
    wells = option["excluded"]
    r = decide(
        c,
        study,
        conseq["card_id"],
        "exclude_flagged",
        expected_head=body["head"],
        expected_inbox=body["inbox_head"],
    )
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "left_out" and done["left_out"] == sorted(wells)
    assert done["put_back"] == [] and done["study_id"] == study
    assert done["message"].startswith(f"Left out {len(wells)} wells")
    assert done["job"] and done["job"]["kind"] == "analyse"
    new = analysed(c, sid, done)
    assert new != study

    # the record: one proposal per well, by Run Gate's rule, accepted by a person with the reason
    inbox = store.proposals(sid)
    mine = [p for p in inbox.proposals(kind_prefix=EXCLUDE_KIND)]
    assert sorted(p.subject for p in mine) == sorted(wells)
    for p in mine:
        assert p.status == "accepted" and p.decided_by == "human" and p.reason == REASON
        assert p.payload == {"excluded": True} and p.made_by.kind == "rule"
        assert p.made_by.provider == GATE_MAKER and p.check.status == "consistent"
        assert p.consequence["gate"]["card_id"] == conseq["card_id"]
        assert p.consequence["matters"] is True
        assert set(p.consequence) == {"matters", "gate"}  # blind-safe: no gene, no number
    entries = inbox.entries()
    assert verify_proposal_chain(entries, inbox.root) is None
    clicks = [e for e in entries if e.proposal_id in {p.id for p in mine}]
    assert {e.actor for e in clicks if e.action == "accept"} == {"human"}
    assert len({e.at for e in clicks}) == 1  # one click, one moment
    assert set(store.design(new).excluded_wells) == set(wells)

    # the new analysis is the one the gate measured: 1-Mar can no longer be compared
    result = store.get(new)
    assert "1-Mar" not in result.contrasts
    assert "1-Mar" in store.get(study).contrasts

    # the gate at the new analysis: the wells are left out, by a person, and why
    after = ready(c, new).json()
    conseq = ntc_card(after)
    (option,) = conseq["options"]
    assert option["code"] == "already_left_out" and option["left_out"] == sorted(wells)
    assert option["text"]["plain"].startswith(f"These {len(wells)} wells are already left out")
    assert conseq["consequence"] == "none" and conseq["card_id"] is None
    assert after["cards"] == []
    decision = conseq["decision"]
    assert decision["option"] == "exclude_flagged" and decision["action"] == "left_out"
    assert decision["reason"] == REASON and decision["decided_by"] == "human"
    assert decision["left_out"] == sorted(wells)
    assert conseq["can_decide"]  # to put them back

    # put them back: the first analysis again
    r = decide(c, new, conseq["decision_id"], "keep", "re-run: the NTC was a pipetting splash")
    assert r.status_code == 200, r.text
    back = r.json()
    assert back["status"] == "put_back" and back["put_back"] == sorted(wells)
    assert analysed(c, sid, back) == study
    again = ready(c, study).json()
    conseq = ntc_card(again)
    assert conseq["decision"]["action"] == "put_back" and conseq["decision"]["option"] == "keep"
    (card,) = again["cards"]
    assert card["card"]["status"] == "decided" and card["card"]["decision"] == "keep"
    assert card["card"]["decided_by"] == "human"
    assert card["status_line"].startswith("Decided by a person: Keep every well")
    assert [o["chosen"] for o in card["options"]] == [True, False]

    # History ties the new analysis to the click that made it, in words, with the reason
    related = c.get(f"/api/studies/{study}/history").json()["related"]
    (made,) = (r for r in related if r["study_id"] == new)
    assert made["after"].startswith(f"Left out {len(wells)} wells (")
    assert made["after"].endswith(f": {REASON}")


def test_keeping_every_well_is_recorded(tainted):
    c, study, sid, store = tainted["client"], tainted["study"], tainted["sid"], tainted["store"]
    body = ready(c, study).json()
    conseq = ntc_card(body)
    r = decide(c, study, conseq["card_id"], "keep", "two NTC replicates stayed flat")
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "kept" and done["job"] is None
    assert done["left_out"] == done["put_back"] == []
    kept = store.proposals(sid).proposals(kind_prefix=EXCLUDE_KIND)
    assert kept and {p.status for p in kept} == {"rejected"}
    assert {p.reason for p in kept} == {"two NTC replicates stayed flat"}
    assert c.get(f"/api/sessions/{sid}").json()["study_id"] == study  # nothing analysed again
    card = ready(c, study).json()["cards"][0]
    assert card["card"]["status"] == "decided" and card["card"]["decision"] == "keep"


def test_an_agent_asks_and_waits_for_a_person(tainted):
    c, study, sid, store = tainted["client"], tainted["study"], tainted["sid"], tainted["store"]
    body = ready(c, study).json()
    card_id = ntc_card(body)["card_id"]
    tools = QpilotTools(store)
    out = tools.qpcr_decide(study, card_id, "exclude_flagged", "the NTC failed")
    assert out["status"] == "pending_human", out
    assert out["proposals"] and all(p["made_by"]["kind"] == "agent" for p in out["proposals"])
    pending = store.proposals(sid).proposals(status="proposed", kind_prefix=EXCLUDE_KIND)
    assert len(pending) == len(out["proposals"])
    assert c.get(f"/api/sessions/{sid}").json()["study_id"] == study  # nothing applied
    view = ready(c, study).json()
    conseq = ntc_card(view)
    (request,) = conseq["requests"]
    assert request["option"] == "exclude_flagged" and request["left_out"]
    assert request["reason"] == "the NTC failed"
    (card,) = view["cards"]
    assert card["pending"][0]["option"] == "exclude_flagged"
    assert [o["requested"] for o in card["options"]] == [False, True]
    assert card["status_line"].startswith("An agent asks for")
    # the person turns it down by keeping every well: the agent's proposals are rejected
    r = decide(c, study, card_id, "keep", "not before the repeat plate")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "kept"
    settled = {p.id: p for p in store.proposals(sid).proposals(kind_prefix=EXCLUDE_KIND)}
    for p in pending:
        assert settled[p.id].status == "rejected"
        assert settled[p.id].reason == "not before the repeat plate"
    # asked again and approved: the agent's own proposals are accepted, no new ones made
    out = tools.qpcr_decide(study, card_id, "exclude_flagged", "the NTC failed again")
    asked = {p["id"] for p in out["proposals"]}
    r = decide(c, study, card_id, "exclude_flagged", "agreed: the NTC failed")
    assert r.status_code == 200, r.text
    accepted = [
        p
        for p in store.proposals(sid).proposals(kind_prefix=EXCLUDE_KIND)
        if p.status == "accepted"
    ]
    assert {p.id for p in accepted} == asked
    assert analysed(c, sid, r.json()) != study


def test_refusals(tainted):
    c, study = tainted["client"], tainted["study"]
    body = ready(c, study).json()
    card_id = ntc_card(body)["card_id"]
    r = decide(c, study, card_id, "exclude_flagged", reason="  ")
    assert r.status_code == 422 and "Say why" in r.json()["error"]["message"]
    r = decide(c, study, card_id, "drop_everything")
    assert r.status_code == 422, r.text
    r = decide(c, study, "card_gate_000000000000", "keep")
    assert r.status_code == 404, r.text
    r = decide(c, study, "card_undetermined", "keep")
    assert r.status_code == 404, r.text
    r = decide(c, study, card_id, "keep", expected_head="0" * 64)
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"
    r = decide(c, study, card_id, "keep", expected_inbox="0" * 64)
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"
    # a check whose wells change no conclusion is not decided here
    flat = [x for x in body["consequences"] if not x["can_decide"]]
    for x in flat:
        r = decide(c, study, x["decision_id"], "keep")
        assert r.status_code == 409 and r.json()["error"]["code"] == "studio", r.text


def test_a_study_analysed_outside_studio_says_where_wells_are_left_out(tainted):
    c, study, sid, store = tainted["client"], tainted["study"], tainted["sid"], tainted["store"]
    design = store.design(study)
    other = store.ensure_study(store.source(study), design.model_copy(update={"design_id": "x"}))
    assert other != study
    body = ready(c, other).json()
    assert body["session"] is None and not body["can_decide"] and body["inbox_head"] is None
    assert "outside Studio" in body["how_to_apply"]
    assert not any(x["can_decide"] for x in body["consequences"])
    card_id = ntc_card(body)["card_id"]
    r = decide(c, other, card_id, "exclude_flagged")
    assert r.status_code == 409 and r.json()["error"]["code"] == "studio"
    assert "open its file in Studio" in r.json()["error"]["message"].replace("Open", "open")
    out = QpilotTools(store).qpcr_decide(other, card_id, "exclude_flagged", "the NTC failed")
    assert "error" in out and "Studio" in out["error"]
    assert not store.proposals(sid).proposals(kind_prefix=EXCLUDE_KIND)


def test_the_gate_tool_reads_the_cards_for_an_agent(tainted):
    store, study = tainted["store"], tainted["study"]
    out = QpilotTools(store).qpcr_gate(study)
    assert out["study_id"] == study and out["counts"]["fail"] >= 1
    (card,) = out["cards"]
    assert card["needs_human"] and card["status"] == "open"
    assert [o["id"] for o in card["options"]] == ["keep", "exclude_flagged"]
    assert "pending_human" in out["how_to_decide"]


def test_nothing_is_decided_or_read_while_the_session_is_blind_again(tainted):
    c, study, sid, store = tainted["client"], tainted["study"], tainted["sid"], tainted["store"]
    card_id = ntc_card(ready(c, study).json())["card_id"]
    studio = studio_of(tainted)
    tools = QpilotTools(store)
    tools.qpcr_propose(sid, "design.group", "WT_1", {"group": "KO"})
    change = next(p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.group")
    studio.accept(sid, change.id, "human", "the lab book says KO")
    assert not studio.results_visible(sid)
    before = store.proposals(sid).head()
    r = decide(c, study, card_id, "exclude_flagged")
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind", r.text
    assert "1-Mar" not in r.text and "flagged" not in r.text
    assert "error" in tools.qpcr_gate(study)
    assert "error" in tools.qpcr_decide(study, card_id, "exclude_flagged", "the NTC failed")
    assert store.proposals(sid).head() == before


def test_a_well_left_out_in_the_curves_inbox_needs_its_own_reason(tainted):
    c, sid, store, study = tainted["client"], tainted["sid"], tainted["store"], tainted["study"]
    well = ntc_card(ready(c, study).json())["options"][0]["excluded"][0]
    out = QpilotTools(store).qpcr_propose(sid, EXCLUDE_KIND, well, {"excluded": True})
    assert out["status"] == "proposed" and out["proposal"]["check"]["status"] == "consistent"
    pid = out["proposal"]["id"]
    assert pid not in studio_of(tainted).consistent_ids(sid, "curves")
    listed = c.get(f"/api/sessions/{sid}/bulk/accept", params={"stage": "curves"}).json()
    assert pid not in listed["ids"]
    head = out["head"]
    r = c.post(
        f"/api/sessions/{sid}/proposals/{pid}/accept", json={"reason": "", "expected_head": head}
    )
    assert r.status_code == 422 and "Say why this well" in r.json()["error"]["message"]
    r = c.post(
        f"/api/sessions/{sid}/proposals/{pid}/accept",
        json={"reason": "a bubble in the well", "expected_head": head},
    )
    assert r.status_code == 200, r.text
    assert analysed(c, sid, r.json()) != study  # a new analysis without the well
