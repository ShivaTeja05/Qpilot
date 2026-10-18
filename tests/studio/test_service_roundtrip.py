"""The round trip on the demo when several values come back excluded together.

Four NM23A units are cleared in Prism. One at a time, none of them changes a conclusion; all four
together turn NM23A's call. Each question's consequence holds only on top of the exclusions a
person already accepted, so the Studio:

- shows on every question what all the exclusions found in the round trip do together;
- recomputes the other questions as soon as a person accepts one;
- refuses to accept a question computed before an exclusion accepted since, and marks its card
  out of date instead of showing its numbers;
- so the numbers a person reads are the ones accepting gives.
"""

import csv
import math
import shutil
from pathlib import Path

import pytest

from qpilot.ai.client import ModelClient, NoneBackend
from qpilot.core.store import StudyStore
from qpilot.studio_service import STALE_EXCLUSIONS, Studio
from qpilot.studio_state import card_html, consequence_html

pytestmark = pytest.mark.demo_data
CLEARED = ("1824", "1936", "2530", "2784")
REASON = "pipetting error"


def _pending(studio: Studio, sid: str) -> list:
    return [p for p in studio.inbox(sid, "roundtrip", "proposed")]


def _accept(studio: Studio, sid: str, proposal) -> str:
    return studio.accept(sid, proposal.id, "human", REASON).status


@pytest.fixture(scope="module")
def trip(tmp_path_factory):
    """Export NM23A, clear four units in Prism, then accept them one by one as the page allows."""
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    root = tmp_path_factory.mktemp("roundtrip")
    studio = Studio(StudyStore(root / "studies"), client=ModelClient(backend=NoneBackend()))
    sid = studio.open(DEMO_RDML)
    studio.propose_design(sid)
    preset = next(p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.preset")
    studio.accept(sid, preset.id, "human")
    studio.accept_all_consistent(sid, "design", "human", studio.consistent_ids(sid, "design"))
    left = studio.inbox(sid, "design", "proposed")
    studio.reject_many(sid, [p.id for p in left], "human", "contradicted by the engine check")
    studio.accept(sid, studio.propose_confirm(sid, "design").proposal.id, "human")
    studio.accept(sid, studio.propose_confirm(sid, "curves").proposal.id, "human")
    study = studio.study(sid)
    for card in studio.store.cards(study):
        if card.status in ("open", "pending_human"):
            head = studio.store.chain_head(study)
            studio.decide(sid, card.id, card.recommended, "checked", "human", head)
    studio.accept(sid, studio.propose_confirm(sid, "choices").proposal.id, "human")
    studio.accept(sid, studio.propose_prism(sid, genes=["NM23A"]).proposal.id, "human")
    bundle = root / "bundle"
    export = studio.send_to_prism(sid, bundle, "human")
    sent_back = root / "sent_back"
    sent_back.mkdir()
    for table in export.bundle.tables:
        shutil.copy(bundle / table.csv, sent_back / Path(table.csv).name)
    table = sent_back / "NM23A.csv"
    with table.open(newline="") as fh:
        rows = list(csv.reader(fh))
    rows = [[r[0], *([""] * (len(r) - 1))] if r and r[0] in CLEARED else r for r in rows]
    with table.open("w", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)

    log: dict = {"studio": studio, "sid": sid, "study": study}
    log["report"] = studio.round_trip(sid, bundle, sent_back)
    log["first"] = _pending(studio, sid)
    visible = studio.results_visible(sid)
    log["first_html"] = [consequence_html(p, results_visible=visible) for p in log["first"]]

    # a person accepts one: the other questions are computed again on top of it
    one = log["first"][0]
    log["one"] = (one, _accept(studio, sid, one))
    log["second"] = _pending(studio, sid)
    log["first_after"] = [studio.store.proposals(sid).get(p.id) for p in log["first"][1:]]

    # the folder Prism sent back to is gone: accepting another cannot recompute the rest
    away = root / "moved"
    sent_back.rename(away)
    two = log["second"][0]
    log["two"] = (two, _accept(studio, sid, two))
    stale = _pending(studio, sid)
    log["stale"] = stale
    log["stale_reasons"] = [studio.stale_consequence(sid, p) for p in stale]
    log["stale_html"] = [
        card_html(p, results_visible=visible, stale=studio.stale_consequence(sid, p)) for p in stale
    ]
    log["stale_accept"] = studio.accept(sid, stale[0].id, "human", REASON)
    log["stale_edit"] = studio.edit(sid, stale[0].id, "human", {"action": "exclude"}, REASON)

    # reading what came back again gives fresh questions; accepting them all
    away.rename(sent_back)
    studio.round_trip(sid, bundle, sent_back)
    fresh = _pending(studio, sid)
    log["fresh"] = fresh
    log["fresh_reasons"] = [studio.stale_consequence(sid, p) for p in fresh]
    last = None
    while _pending(studio, sid):
        last = _pending(studio, sid)[0]
        assert _accept(studio, sid, last) == "accepted"
    log["last"] = last
    final = studio.study(sid)
    log["final"] = studio.store.get(final).contrasts["NM23A"]
    log["accepted"] = studio.store.proposals(sid).accepted("prism.exclusion_reason")
    return log


def test_every_question_says_what_all_the_exclusions_do_together(trip):
    first, combined = trip["first"], trip["report"]["combined_consequence"]
    assert len(first) == len(CLEARED)
    assert combined is not None and len(combined["exclusions"]) == len(CLEARED)
    assert "NM23A" in combined["changed_genes"]  # together they turn NM23A's call
    for proposal, html in zip(first, trip["first_html"], strict=True):
        c = proposal.consequence
        assert c["n_conclusions_changed"] == 0  # one at a time, none of them changes anything
        assert c["basis"]["accepted"] == []
        together = c["with_all_pending"]
        assert together["n_exclusions"] == len(CLEARED)
        assert math.isclose(together["fc_after"], combined["genes"]["NM23A"]["fc_after"])
        assert together["conclusion_after"] != together["conclusion_before"]
        assert "On its own it changes no conclusion, but together" in html


def test_accepting_one_recomputes_the_others_on_top_of_it(trip):
    one, status = trip["one"]
    assert status == "accepted"
    second = trip["second"]
    assert len(second) == len(CLEARED) - 1
    assert not {p.id for p in second} & {p.id for p in trip["first"]}
    assert all(p.status == "superseded" for p in trip["first_after"])
    for proposal in second:
        c = proposal.consequence
        assert c["basis"]["accepted"] == [one.id]
        assert math.isclose(c["fc_before"], one.consequence["fc_after"], rel_tol=1e-12)
        together = c["with_all_pending"]  # the other three on top of the accepted one = all four
        all_four = trip["report"]["combined_consequence"]["genes"]["NM23A"]
        assert math.isclose(together["fc_after"], all_four["fc_after"], rel_tol=1e-12)


def test_a_question_computed_before_an_accept_since_is_refused_and_shown_out_of_date(trip):
    _, status = trip["two"]
    assert status == "accepted"
    assert trip["stale"] and all(r == STALE_EXCLUSIONS for r in trip["stale_reasons"])
    for html in trip["stale_html"]:
        assert "Out of date" in html and "×" not in html  # none of its numbers is shown
    for outcome in (trip["stale_accept"], trip["stale_edit"]):
        assert outcome.status == "refused" and STALE_EXCLUSIONS in outcome.reason
    assert trip["fresh"] and trip["fresh_reasons"] == [None] * len(trip["fresh"])


def test_the_numbers_a_person_read_are_what_accepting_gives(trip):
    assert len(trip["accepted"]) == len(CLEARED)
    last, final = trip["last"].consequence, trip["final"]
    assert math.isclose(final.fc, last["fc_after"], rel_tol=1e-9)
    assert final.conclusion == last["conclusion_after"]
    all_four = trip["report"]["combined_consequence"]["genes"]["NM23A"]
    assert math.isclose(final.fc, all_four["fc_after"], rel_tol=1e-9)
    assert final.conclusion == all_four["conclusion_after"] != all_four["conclusion_before"]
