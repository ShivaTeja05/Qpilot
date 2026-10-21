"""The Import Trust card over HTTP (and MCP): read it, decide it, and the cap the genes carry.

The mini file walked in Studio as if opened from a CFX export whose curves were
baseline-subtracted (``tests/fixtures/studio/trust.py``):

* ``GET /api/studies/{id}/import-trust`` answers the card (options with their caps, the vendor's
  recipe, the option in use) for that session's study, and ``applies: false`` for a study whose
  curves call for no card (an RDML file, Rn) or one analysed outside Studio;
* ``POST …/import-trust/decide`` records a person's choice in the session's inbox; Cq only
  analyses the study again (the ``analyse`` job) and every gene is capped at Low there;
* an agent's ``qpcr_decide`` on ``card_import_trust`` is ``pending_human`` and waits on the card;
* refusals: blind (403) for both routes, no reason / no such option (422), outside Studio and no
  card (409 studio), a moved analysis or inbox (409 stale).
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.mcp_server import QpilotTools
from qpilot.studio_service import TRUST_KIND
from qpilot.web import intake
from qpilot.web.context import make_context
from qpilot.web.server import create_app
from tests.fixtures.studio import trust as fixture
from tests.web.conftest import BASE, TOKEN, wait_job

REASON = "the CFX export was baseline-subtracted; we report the instrument's Cq values"


@pytest.fixture(scope="module")
def trusted_walked(tmp_path_factory):
    """The mini file walked as an instrument export with baseline-subtracted curves (once)."""
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect
    from qpilot.studio_service import Studio

    base = tmp_path_factory.mktemp("trusted-web")
    root = base / "data"
    root.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_DATA_ROOTS", str(root))
        mp.setenv("QPILOT_STUDIES_DIR", str(base / "studies"))
        qinspect.clear_cache()
        rdml = fixture.write_trusted_mini(root)
        studio = Studio(StudyStore(base / "studies"), client=ModelClient(backend=NoneBackend()))
        sid, study = fixture.walk_trusted(studio, rdml)
        design_checks._DECLARED.clear()
        design_checks.set_input_resolver(None)
        qinspect.clear_cache()
    return {"base": base, "root": root, "sid": sid, "study": study}


@pytest.fixture
def trusted(trusted_walked, tmp_path, monkeypatch):
    """A private copy of the walked store, its server context and a keyed client."""
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect
    from qpilot.studio_service import Studio

    shutil.copytree(trusted_walked["base"], tmp_path / "w", symlinks=False)
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(trusted_walked["root"]))
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(tmp_path / "w" / "studies"))
    qinspect.clear_cache()
    store = StudyStore(tmp_path / "w" / "studies")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    ctx = make_context(store, studio, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE
        yield {"client": c, "store": store, "studio": studio, "ctx": ctx, **trusted_walked}
    ctx.close()
    design_checks._DECLARED.clear()
    design_checks.set_input_resolver(None)
    qinspect.clear_cache()


def card(c: TestClient, study: str) -> dict:
    r = c.get(f"/api/studies/{study}/import-trust")
    assert r.status_code == 200, r.text
    return r.json()


def decide(c: TestClient, study: str, option: str, reason: str = REASON, **extra):
    return c.post(
        f"/api/studies/{study}/import-trust/decide",
        json={"option": option, "reason": reason, **extra},
    )


def analysed(c: TestClient, sid: str, answer: dict) -> str:
    """Wait for the analysis a decision started; the session's study id after it."""
    if answer.get("job"):
        job = wait_job(c, answer["job"])
        assert job["status"] == "done", job
    frame = c.get(f"/api/sessions/{sid}").json()
    assert frame["results_visible"]
    return frame["study_id"]


def levels(c: TestClient, study: str) -> dict[str, tuple[str, list[str]]]:
    genes = c.get(f"/api/studies/{study}/results").json()["genes"]
    return {g["gene"]: (g["level"], g["reasons"]) for g in genes}


def test_the_card_before_anyone_decides(trusted):
    c, study, sid = trusted["client"], trusted["study"], trusted["sid"]
    body = card(c, study)
    assert body["applies"] and body["why"] == ""
    assert body["card_id"] == "card_import_trust" and body["kind"] == "capture.import_trust"
    assert body["verdict"] == "baseline_subtracted"
    assert body["verdict_title"] == "Baseline already subtracted"
    assert "No Baseline Subtraction" in body["recipe"]
    assert body["connector_label"].startswith("Bio-Rad CFX")
    assert body["n_instrument_cq"] == 49 and body["n_wells"] == 60
    assert [p["verdict"] for p in body["plates"]] == ["baseline_subtracted"] * 2
    assert body["status"] == "open" and body["decision"] is None and body["requests"] == []
    assert body["in_use"] == "analyse_as_is" and body["cap"] == "Moderate"
    assert "vendor-baselined curves" in body["cap_reason"]
    assert body["can_decide"] and body["inbox_head"] == trusted["studio"].head(sid)
    options = {o["id"]: o for o in body["options"]}
    assert list(options) == ["reexport_raw", "analyse_as_is", "cq_only"]
    assert options["reexport_raw"]["recommended"] and not options["cq_only"]["recommended"]
    assert options["analyse_as_is"]["in_use"]
    assert {o: x["cap"] for o, x in options.items()} == {
        "reexport_raw": "Moderate",
        "analyse_as_is": "Moderate",
        "cq_only": "Low",
    }
    assert [o for o, x in options.items() if x["new_analysis"]] == ["cq_only"]
    assert all(x["available"] for x in options.values())
    assert "Decision Cards" in body["decide_note"]
    # every gene is capped, and says so when the cap is what holds it down
    for level, _ in levels(c, study).values():
        assert level in ("Moderate", "Low", "Very low")
    capture = c.get(f"/api/sessions/{sid}").json()["capture"]
    assert capture["rawness"]["import_trust"] is True


def test_cq_only_is_decided_here_and_the_study_is_analysed_again(trusted):
    c, study, sid, studio = trusted["client"], trusted["study"], trusted["sid"], trusted["studio"]
    head = card(c, study)["inbox_head"]
    r = decide(c, study, "cq_only", expected_inbox=head)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "decided" and done["option"] == "cq_only" and done["changed"]
    assert "instrument's Cq values" in done["message"] and done["job"] is not None
    assert done["inbox_head"] == studio.head(sid)
    cq = analysed(c, sid, done)
    assert cq != study
    body = card(c, cq)
    assert body["status"] == "decided" and body["in_use"] == "cq_only" and body["cap"] == "Low"
    assert body["decision"]["option"] == "cq_only" and body["decision"]["reason"] == REASON
    assert body["decision"]["decided_by"] == "human" and body["decision"]["decided_at"]
    assert [o["id"] for o in body["options"] if o["new_analysis"]] == [
        "reexport_raw",
        "analyse_as_is",
    ]
    ((level, reasons),) = levels(c, cq).values()
    assert level == "Low" and "efficiency assumed" in reasons[-1]
    # the earlier analysis is not the one in use any more: read-only, and stale to decide
    old = card(c, study)
    assert old["applies"] and not old["can_decide"] and "not the analysis in use" in old["why"]
    r = decide(c, study, "analyse_as_is")
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"
    # back to the curves as imported: the first analysis again
    back = decide(c, cq, "analyse_as_is").json()
    assert back["changed"] and "analysed again" in back["message"]
    assert analysed(c, sid, back) == study
    assert card(c, study)["decision"]["option"] == "analyse_as_is"


def test_keeping_the_analysis_records_the_choice_without_a_new_analysis(trusted):
    c, study, sid = trusted["client"], trusted["study"], trusted["sid"]
    r = decide(c, study, "reexport_raw")
    assert r.status_code == 200, r.text
    done = r.json()
    assert not done["changed"] and done["job"] is None
    assert "open the raw export as a new study" in done["message"]
    assert c.get(f"/api/sessions/{sid}").json()["study_id"] == study
    body = card(c, study)
    assert body["in_use"] == "reexport_raw" and body["cap"] == "Moderate"
    assert body["decision"]["label"] == "Re-export the raw curves"
    r = decide(c, study, "reexport_raw")
    assert r.status_code == 409 and r.json()["error"]["code"] == "studio"
    assert "already the decision" in r.json()["error"]["message"]
    # the choice is in the Curves inbox like any proposal, accepted by the person
    listed = c.get(f"/api/sessions/{sid}/proposals", params={"stage": "curves"}).json()
    (mine,) = (p for p in listed["proposals"] if p["kind"] == TRUST_KIND)
    assert mine["status"] == "accepted"


def test_refusals(trusted):
    c, study = trusted["client"], trusted["study"]
    for option, reason, code in (
        ("cq_only", "  ", "bad_request"),
        ("trust_me", REASON, "bad_request"),
    ):
        r = decide(c, study, option, reason)
        assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text
    stale = decide(c, study, "cq_only", expected_inbox="0" * 64)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale"
    assert c.get("/api/studies/0123456789ab/import-trust").status_code == 404
    assert card(c, study)["decision"] is None  # nothing was written


def test_a_study_analysed_outside_studio_has_no_card_here(trusted):
    c, study, store = trusted["client"], trusted["study"], trusted["store"]
    design = store.design(study)
    other = store.ensure_study(store.source(study), design.model_copy(update={"design_id": "x"}))
    body = card(c, other)
    assert not body["applies"] and "outside Studio" in body["why"]
    r = decide(c, other, "cq_only")
    assert r.status_code == 409 and r.json()["error"]["code"] == "studio"
    out = QpilotTools(store).qpcr_decide(other, "card_import_trust", "cq_only", "Delta Rn")
    assert "error" in out and "outside Studio" in out["error"]


@pytest.mark.parametrize("verdict", ["normalized", "raw"])
def test_curves_that_call_for_no_card(trusted, verdict):
    c, sid, store, studio = trusted["client"], trusted["sid"], trusted["store"], trusted["studio"]
    intake.save(store, sid, fixture.capture_meta(verdict), [])
    plain = studio.study(sid)
    body = card(c, plain)
    assert not body["applies"] and "call for no Import Trust decision" in body["why"]
    r = decide(c, plain, "analyse_as_is")
    assert r.status_code == 409 and r.json()["error"]["code"] == "studio"
    assert c.get(f"/api/sessions/{sid}").json()["capture"]["rawness"]["import_trust"] is False
    for _, reasons in levels(c, plain).values():
        assert not any("qPilot caps confidence" in r for r in reasons)


def test_both_routes_are_blind_until_the_session_is_confirmed_again(trusted):
    c, study, sid, studio = trusted["client"], trusted["study"], trusted["sid"], trusted["studio"]
    assert card(c, study)["applies"]
    QpilotTools(trusted["store"]).qpcr_propose(sid, "design.group", "WT_1", {"group": "KO"})
    change = next(p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.group")
    studio.accept(sid, change.id, "human", "the lab book says KO")
    r = c.get(f"/api/studies/{study}/import-trust")
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind", r.text
    assert "cap" not in r.text and "verdict" not in r.text
    r = decide(c, study, "cq_only")
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind", r.text
    assert not [p for p in studio.inbox(sid, "curves") if p.kind == TRUST_KIND]


def test_an_agent_asks_over_mcp_and_a_person_answers_on_the_card(trusted):
    c, study, sid, store = trusted["client"], trusted["study"], trusted["sid"], trusted["store"]
    tools = QpilotTools(store)
    seen = tools.qpcr_study(str(store.source(study)), design={"session": sid})
    assert seen["study_id"] == study
    listed = seen["import_trust"]
    assert listed["card_id"] == "card_import_trust" and listed["needs_human"]
    assert listed["in_use"] == "analyse_as_is" and listed["cap"]["level"] == "Moderate"
    out = tools.qpcr_decide(study, "card_import_trust", "cq_only", "the export holds Delta Rn")
    assert out["status"] == "pending_human", out
    assert "Only a person" in out["reason"] and len(out["proposals"]) == 1
    assert tools.qpcr_decide(study, "card_import_trust", "nope", "x")["error"].startswith("unknown")
    body = card(c, study)
    assert body["status"] == "pending_human"
    (request,) = body["requests"]
    assert request["option"] == "cq_only" and request["reason"] == "the export holds Delta Rn"
    assert c.get(f"/api/sessions/{sid}").json()["study_id"] == study  # nothing applied
    done = decide(c, study, "analyse_as_is").json()  # the person chooses otherwise
    assert not done["changed"]
    body = card(c, study)
    assert body["requests"] == [] and body["decision"]["option"] == "analyse_as_is"
    (asked,) = (p for p in trusted["studio"].inbox(sid, "curves") if p.made_by.kind == "agent")
    assert asked.status == "rejected" and asked.reason == REASON  # turned down by the click


def test_the_decide_route_is_in_the_blind_sweep():
    """The red team's sweep posts BODIES["decide"] to every ``…/decide`` study route."""
    from qpilot.web.contract_trust import TrustDecide
    from tests.web.test_redteam_blind import BODIES

    TrustDecide.model_validate(BODIES["decide"])  # a valid body: the gate answers, not a 422
