"""The Claim Auditor on a study with several comparisons (science review, October 2026).

The record's contrasts are the first comparison's (Drug A against Control in the synthetic
three-group file). Before the fix a claim about Drug B was read against Drug A's numbers:
"MYC was up-regulated in Drug B compared with Control" came back Overstated (the study calls it
up there, Holm-corrected p 0.028) and "IL6 was higher in Drug B than in Drug A" Contradicted (a
pair the plan does not even compare). Such a claim is now Unchecked, in words that say why; a
claim that names no group says it was read against the first comparison; and "significant" is
judged by the corrected p, the one the call uses.
"""

from __future__ import annotations

import dataclasses

import pytest

from qpilot.claims import StudyRecord, audit_text
from qpilot.claims.lexicon import Lexicon
from qpilot.qpcr.contrast import ConclusionRule
from qpilot.qpcr.study import StudySettings, run_study
from tests.fixtures.studio.compare_mini import design as mini_design
from tests.fixtures.studio.compare_mini import write_compare_mini


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    root = tmp_path_factory.mktemp("claims-compare")
    return write_compare_mini(root / "compare_mini.rdml"), root / "cache"


def _record(mini, rule=None) -> StudyRecord:
    path, cache = mini
    design = mini_design(paired=False, correction="holm")
    settings = StudySettings.from_design(design)
    if rule is not None:
        settings = dataclasses.replace(settings, rule=rule)
    result = run_study(path, settings, cache_dir=cache)[0]
    return StudyRecord(
        study_id=result.study_id, result=result, lexicon=Lexicon.from_study(result, design)
    )


@pytest.mark.parametrize(
    "text",
    [
        "MYC was up-regulated in Drug B compared with Control.",
        "IL6 was higher in Drug B than in Drug A.",
        "MYC was higher in Drug B than in Drug A.",
    ],
)
def test_a_claim_about_another_comparison_is_not_read_against_the_first(mini, text):
    (claim,) = audit_text(text, _record(mini)).claims
    assert claim.verdict == "unchecked", claim.headline.plain
    assert "“Drug B”" in claim.headline.plain
    assert "first comparison only (Drug A against Control)" in claim.headline.plain


def test_the_first_comparisons_claims_are_checked_as_before(mini):
    record = _record(mini)
    (claim,) = audit_text("IL6 was up-regulated in Drug A compared with Control.", record).claims
    assert claim.verdict == "supported"
    (claim,) = audit_text("MYC did not change.", record).claims
    assert claim.verdict == "supported"
    notes = [c.text.plain for c in claim.checks if c.check == "groups"]
    assert notes == [
        "This study has several comparisons; with no group named, the claim is read against "
        "the first, Drug A against Control."
    ]


def test_significant_is_judged_by_the_corrected_p(mini):
    """IL6, Drug A against Control: raw p 0.0011, Holm-corrected 0.0022; a rule at 0.002."""
    record = _record(mini, ConclusionRule(alpha=0.002))
    first = record.result.comparisons.comparisons[0]
    assert record.result.contrasts["IL6"].p < 0.002 < first.p_adjusted["IL6"]
    text = "IL6 was significantly higher in Drug A than in Control."
    (claim,) = audit_text(text, record).claims
    (check,) = [c for c in claim.checks if c.check == "significance"]
    assert check.status == "stronger"
    assert check.text.plain.startswith("The study's corrected p for IL6, 0.0022, is not below")
