"""N3 Run Review (thin): ledger, headline and sign-offs on the fixture study and the demo.

The vocabulary check uses ``qpilot.core.vocabulary`` when it exists, else the BUILD-DESIGN §0
list below.
"""

import html
import re

import pytest

from qpilot.core.store import StudyStore
from qpilot.core.validator import validate
from qpilot.explain.evidence_text import REVIEW_NOT_BUILT, runreview_text
from qpilot.qpcr.evidence import ITEMS
from qpilot.report.run_review import (
    CALL_WORDS,
    RunReview,
    RunReviewError,
    build_review,
    render_html,
    render_text,
    run_review,
)
from tests.engine.evidence_toys import toy_design, toy_model, toy_table

BANNED = ("diagnosis", "diagnose", "root cause", "detects inhibition", "error found", "validated",
          "valid run", "invalid run", "faulty instrument", "compliant", "IVD")  # fmt: skip


def banned_words(text: str) -> list[str]:
    try:
        from qpilot.core.vocabulary import banned_words as found  # the foundation's lint
    except ImportError:
        return [w for w in BANNED if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.I)]
    return found(text)


def visible(page: str) -> str:
    """The text a reader sees: no style block, no tags."""
    page = re.sub(r"<style>.*?</style>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def review_entry(seq=5, **update):
    entry = {
        "seq": seq,
        "prev_hash": "ab" * 32,
        "card_id": "run_review",
        "option": "accept",
        "reason": "Looked at the controls with the trainee.",
        "actor": "human",
        "status": "applied",
        "at": "2026-10-18T09:15:00Z",
        "hash": "cd" * 32,
        "kind": "review",
        "outcome": "accept",
        "reviewer": "Dr Rossi",
    }
    entry.update(update)
    return entry


@pytest.fixture
def stored(tmp_studies_dir, fixture_result, fixture_cards):
    store = StudyStore(tmp_studies_dir)
    store.put(fixture_result, fixture_cards)
    return store, fixture_result.study_id


@pytest.fixture(scope="module")
def toy_ledger():
    from qpilot.qpcr.evidence import evidence_for

    table, design = toy_table(), toy_design()
    return evidence_for(table, toy_model(table, design), design)


def test_review_of_the_fixture_study_with_a_ledger(stored, toy_ledger):
    store, sid = stored
    review = run_review(store, sid, reviews=[review_entry()], ledger=toy_ledger)
    assert isinstance(review, RunReview) and review.study_id == sid
    assert [g.gene for g in review.headline] == ["ODC1", "BIRC5", "NTRK1", "NM23A"]
    assert {g.gene: g.level for g in review.headline} == {
        "ODC1": "Moderate", "BIRC5": "Moderate", "NTRK1": "Moderate", "NM23A": "Very low",
    }  # fmt: skip
    assert review.headline[2].conclusion == "down"
    assert [r.outcome for r in review.reviews] == ["accept"]
    assert [n.id for n in review.not_available] == ["next_run"]
    tokens = review.tokens()
    assert validate(tokens, review.facts).ok
    text = render_text(review)
    assert (
        "ODC1: called up, 3.6× (Moderate confidence; holds in 100% of the 186 analyses "
        "qPilot checks)." in text
    )
    assert "NTRK1: called down" in text
    assert "Dr Rossi chose accept on 2026-10-18T09:15:00Z (decision-log entry 5)" in text
    assert "What to repeat and why: in qPilot's Run Review" in text  # rendered without a plan
    assert "Run Gate lines per plate: in qPilot's Controls section" in text
    assert "not built" not in text and "not available yet; the repeat" not in text
    for item in ITEMS:
        assert review.facts[f"f_ev_{item}_status"].value == toy_ledger.item(item).status


def test_every_number_on_the_page_is_a_fact(stored, toy_ledger):
    store, sid = stored
    review = run_review(store, sid, reviews=[review_entry()], ledger=toy_ledger)
    page = render_html(review)
    body = visible(page)
    without_facts = re.sub(r'<span class="fact"[^>]*>.*?</span>', " ", page, flags=re.S)
    without_facts = visible(without_facts)
    assert not re.search(r"\d", without_facts), re.findall(r"\S*\d\S*", without_facts)[:5]
    assert "{{" not in page and "3.6×" in body
    assert page.startswith("<!doctype html>") and "<script" not in page and "http" not in page


def test_names_and_comments_are_escaped(stored, toy_ledger):
    store, sid = stored
    hostile = review_entry(reviewer="<img src=x onerror=alert(1)>",
                           reason="<script>alert('x')</script> & more")  # fmt: skip
    review = run_review(store, sid, reviews=[hostile], ledger=toy_ledger)
    page = render_html(review)
    assert "<script>" not in page and "<img" not in page
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; &amp; more" in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page


def test_the_page_never_judges_the_run(stored, toy_ledger):
    store, sid = stored
    for reviews in ([], [review_entry(), review_entry(seq=7, outcome="repeat", reason="")]):
        review = run_review(store, sid, reviews=reviews, ledger=toy_ledger)
        for text in (render_text(review), visible(render_html(review)), review.tokens()):
            assert banned_words(text) == []
            assert "valid run" not in text.lower() and "passed" not in text.lower()
    assert "No sign-off is recorded yet." in render_text(run_review(store, sid, ledger=toy_ledger))


def test_without_the_input_file_the_ledger_is_not_available(stored):
    store, sid = stored
    review = run_review(store, sid)
    assert review.ledger is None and "input file" in review.ledger_note
    text = render_text(review)
    assert "The Evidence Ledger is not available for this study: the input file" in text
    assert validate(review.tokens(), review.facts).ok
    assert not any(fid.startswith("f_ev_") for fid in review.facts)


def test_a_stored_ledger_is_used_when_the_store_holds_artifacts(stored, toy_ledger):
    store, sid = stored

    class ArtifactStore:
        def __getattr__(self, name):
            return getattr(store, name)

        def get_artifact(self, study_id, name):
            assert name == "evidence.json"
            return toy_ledger.model_dump(mode="json")

    review = run_review(ArtifactStore(), sid)
    assert review.ledger == toy_ledger


def test_sign_offs_are_ordered_and_checked(stored, toy_ledger):
    store, sid = stored
    first, second = review_entry(seq=9, outcome="discuss"), review_entry(seq=4)
    review = run_review(store, sid, reviews=[first, second], ledger=toy_ledger)
    assert [r.seq for r in review.reviews] == [4, 9]
    text = render_text(review)
    assert text.index("(decision-log entry 4)") < text.index("(decision-log entry 9)")
    for bad, message in [
        ({**review_entry(), "kind": None}, "kind 'review'"),
        (review_entry(outcome="approve", option="approve"), "outcome"),
        (review_entry(reviewer=" "), "reviewer"),
        (review_entry(seq="3"), "sequence"),
    ]:
        with pytest.raises(RunReviewError, match=message):
            run_review(store, sid, reviews=[bad], ledger=toy_ledger)
    with pytest.raises(RunReviewError, match="share"):
        run_review(store, sid, reviews=[review_entry(), review_entry()], ledger=toy_ledger)
    with pytest.raises(RunReviewError, match="mapping"):
        run_review(store, sid, reviews=["accept"], ledger=toy_ledger)


def test_option_stands_in_for_outcome_and_models_are_accepted(stored, toy_ledger):
    from pydantic import BaseModel

    class Entry(BaseModel):
        seq: int
        kind: str
        option: str
        reviewer: str
        reason: str = ""
        at: str = ""

    store, sid = stored
    entry = Entry(seq=2, kind="review", option="repeat", reviewer="PI")
    review = run_review(store, sid, reviews=[entry], ledger=toy_ledger)
    assert review.reviews[0].outcome == "repeat" and review.reviews[0].comment == ""
    assert "PI chose repeat (decision-log entry 2)." in render_text(review)


def test_a_ledger_of_another_study_is_refused(fixture_result, toy_ledger):
    other = toy_ledger.model_copy(update={"study_id": "ffffffffffff"})
    with pytest.raises(RunReviewError, match="another study"):
        build_review(fixture_result, ledger=other)


def test_headline_genes_the_study_lacks_are_left_out(fixture_result):
    review = build_review(fixture_result, headline=("NOT_A_GENE", "ODC1", "ODC1"))
    assert [g.gene for g in review.headline] == ["ODC1"]
    empty = build_review(fixture_result, headline=())
    assert "No headline genes are named for this study." in render_text(empty)
    assert set(CALL_WORDS) == {"up", "down", "none"}


def test_the_review_is_deterministic(stored, toy_ledger):
    store, sid = stored
    a = run_review(store, sid, reviews=[review_entry()], ledger=toy_ledger)
    b = run_review(store, sid, reviews=[review_entry()], ledger=toy_ledger)
    assert a.model_dump_json() == b.model_dump_json()
    assert render_html(a) == render_html(b) and render_text(a) == render_text(b)


def test_the_facts_only_template_degrades(fixture_facts):
    for facts in ({}, fixture_facts):
        text = runreview_text(facts)
        assert text == REVIEW_NOT_BUILT and validate(text, facts).ok
        assert not re.search(r"\d", text)


@pytest.mark.demo_data
def test_demo_run_review(tmp_studies_dir, demo_rdml_path):
    store = StudyStore(tmp_studies_dir)
    sid = store.ensure_study(demo_rdml_path)
    review = run_review(store, sid, reviews=[review_entry(outcome="discuss")])
    assert review.ledger is not None and review.ledger.study_id == sid
    assert review.ledger.statuses()["no_rt"] == "absent"
    assert review.ledger.statuses()["inter_run_calibrator"] == "not_applicable"
    text = render_text(review)
    assert "64 plates, 366 samples, 24,576 reactions" in text
    assert (
        "Evidence Ledger: 3 of 11 items present, 6 absent, 1 unknown and 1 not applicable" in text
    )
    assert "RT variability not measured" in text
    assert (
        "NM23A: called up, 2.2× (Very low confidence; holds in 65% of the 186 analyses "
        "qPilot checks)." in text
    )
    page = render_html(review)
    assert banned_words(visible(page)) == [] and banned_words(text) == []
    assert validate(review.tokens(), review.facts).ok
