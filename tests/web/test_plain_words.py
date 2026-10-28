"""Plain words the whole product shares: counted nouns, the Curve Judge's sentence said once,
one display name for a group, and who decided."""

from __future__ import annotations

from qpilot.app_state import decider_words
from qpilot.explain.words import noun, plural
from qpilot.studio_service import CURVE_JUDGE_LISTED
from qpilot.web.studio_views import curve_judge_sentence, report_message


def test_counted_nouns_never_say_s_in_brackets() -> None:
    assert plural(1, "well") == "1 well"
    assert plural(3, "well") == "3 wells"
    assert plural(2, "analysis", "analyses") == "2 analyses"
    assert noun(1, "plate") == "plate" and noun(0, "plate") == "plates"


def test_the_curve_judge_sentence_is_said_once() -> None:
    report = {
        "proposed": ["p"] * 111,
        "notes": [CURVE_JUDGE_LISTED],
        "disagreements": 166,
        "targets_that_matter": 1,
    }
    text = report_message(report, "curves")
    assert text.count("Curve Judge") == 1
    assert "(s)" not in text
    assert "on 1 target, resolving them could change a conclusion" in text
    assert "listed one well each" not in text  # the note is folded into the sentence
    # without the Curve Judge's counts the note is still said
    assert "listed one well each" in report_message({"notes": [CURVE_JUDGE_LISTED]}, "curves")


def test_the_curve_judge_sentence_counts_properly() -> None:
    assert curve_judge_sentence({"disagreements": 0}).endswith("every study well it scored.")
    one = curve_judge_sentence({"disagreements": 1, "targets_that_matter": 0})
    assert one.startswith("The Curve Judge disagrees with LinRegPCR on 1 study well;")
    assert "it is not listed" in one
    two = curve_judge_sentence({"disagreements": 9, "targets_that_matter": 2})
    assert "on 2 targets" in two and "those targets' wells" in two


def test_who_decided_is_one_wording() -> None:
    assert decider_words("human") == "you"
    assert decider_words("agent") == "an agent"
    assert decider_words("system") == "qPilot"
