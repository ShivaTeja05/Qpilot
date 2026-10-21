"""The vocabulary lint: banned status words are found, the disclaimers and command names pass."""

import pytest

import qpilot
from qpilot.app_state import FOOTER
from qpilot.core.validator import names_from_result
from qpilot.core.vocabulary import ALLOWED_PHRASES, BANNED, banned_words
from qpilot.explain.templates import TEMPLATES, render_template
from qpilot.mcp_server import INSTRUCTIONS


@pytest.mark.parametrize("term", BANNED)
def test_every_banned_term_is_found_in_any_case(term):
    for text in (term, term.upper(), term.title(), term.lower()):
        assert banned_words(f"The run is {text}, they said.") == [term]


@pytest.mark.parametrize(
    "text",
    [
        "Run qpilot validate on the folder.",
        "The validation folder holds the benchmark.",
        "This check validates the parser.",
        "genorm_validated is a key, {{f_validated}} a token.",
        "The record is invalidated by any edit.",
        "IVDH is a gene symbol; so is IVDX.",
        "Compliance is a separate question.",
        "A valid comparison needs replicates.",
        "Root of the tree, cause of the shift.",
        "The values are consistent with a pipetting slip; what to check: well K22.",
        "Cannot tell from biology without replicates.",
        "",
    ],
)
def test_clean_text_passes(text):
    assert banned_words(text) == []


def test_multi_word_terms_match_across_line_breaks_and_hyphens():
    assert banned_words("a root-cause analysis") == ["root cause"]
    assert banned_words("an invalid\nrun and an error\tfound") == ["invalid run", "error found"]
    assert banned_words("Root  Causes") == ["root causes"]


def test_terms_come_back_once_in_order_and_as_written_in_banned():
    text = "Validated. A diagnosis. ivd. VALIDATED again, then ivds and valid runs."
    assert banned_words(text) == ["validated", "diagnosis", "IVD", "IVDs", "valid runs"]


def test_a_longer_term_is_found_whole():
    assert banned_words("two invalid runs") == ["invalid runs"]
    assert banned_words("the faulty instruments") == ["faulty instruments"]


@pytest.mark.parametrize(
    "text",
    [
        qpilot.__doc__.splitlines()[2],
        *FOOTER,
        INSTRUCTIONS,
        "For research use only. Not for clinical or\n    diagnostic use.",
        "NOT FOR DIAGNOSTIC USE",
        "qPilot is not Part 11 compliant.",
    ],
)
def test_the_disclaimers_pass(text):
    assert banned_words(text) == []


def test_the_research_use_disclaimer_is_the_one_in_the_code():
    assert "Not for clinical or diagnostic use." in qpilot.__doc__
    assert "not for clinical or diagnostic use" in INSTRUCTIONS
    assert ALLOWED_PHRASES[0] == "not for clinical or diagnostic use"


def test_a_banned_word_beside_a_disclaimer_is_still_found():
    text = "Not for clinical or diagnostic use. This is a diagnostic result."
    assert banned_words(text) == ["diagnostic"]
    assert banned_words("not for diagnostic use; diagnosed by qPilot") == ["diagnosed"]


def test_allowed_names_are_removed_before_the_scan():
    assert banned_words("IVD is up 2-fold") == ["IVD"]
    assert banned_words("IVD is up", allowed_names=["IVD"]) == []
    assert banned_words("ivd and IVD", allowed_names=["IVD", ""]) == []
    assert banned_words("IVD is up, the run is validated", allowed_names=["IVD"]) == ["validated"]


def test_every_registered_template_renders_clean_from_the_fixture_facts(
    fixture_result, fixture_cards
):
    facts, names = fixture_result.facts, names_from_result(fixture_result)
    for key in TEMPLATES:
        genes = list(fixture_result.confidence) if key == "confidence_v1" else [None]
        for gene in genes:
            text = render_template(key, facts, gene=gene).plain
            assert banned_words(text, names) == [], (key, gene)
    for card in fixture_cards:
        text = render_template(card.rationale_template, facts, card=card).plain
        assert banned_words(text, names) == [], card.id
