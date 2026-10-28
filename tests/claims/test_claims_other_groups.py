"""A claim about groups the study does not compare is never "Supported" (science review, Oct 2026).

The review wrote 20 sentences about groupings the demo study does not make (it splits tumours by
MYCN expression) and 15 about its own groups, written in other words than the corpus's. Before
the fix 9 of the 20 came back "Supported": a longer phrase that names another grouping lost to
the study's group inside it ("high MYCN copy number" read as "high MYCN"), plural statuses
("ALK mutations"), chromosomal changes ("1p-deleted", "11q loss"), age, clinical outcome and
experimental conditions were not recognised. One known gap stays (``MNA``, the field's own
abbreviation of MYCN amplification): see ``docs/science-review-2026-10.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qpilot.claims import StudyRecord, audit_text
from qpilot.claims.lexicon import Lexicon
from qpilot.schemas import StudyResult

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "results.json"

OTHER = [
    ("BIRC5 was higher in tumours with a high MYCN copy number.", "MYCN copy number"),
    ("BIRC5 was higher in tumours with high MYCN amplification.", "MYCN amplification"),
    ("BIRC5 was higher in 1p-deleted tumours.", "a chromosomal change"),
    ("BIRC5 was higher in tumours with 11q loss.", "a chromosomal change"),
    ("BIRC5 was higher in tumours with loss of chromosome 17p.", "a chromosomal change"),
    ("BIRC5 was higher in tumours with ALK mutations.", "ALK status"),
    ("BIRC5 was higher in tumours with MYCN mutations.", "MYCN mutation"),
    ("BIRC5 was higher in tumours from patients older than 18 months.", "age"),
    ("BIRC5 was higher in tumours with unfavourable histology.", "clinical course"),
    ("BIRC5 was higher in patients who died of disease.", "clinical course"),
    ("BIRC5 was higher under hypoxia than under normoxia.", "an experimental condition"),
    ("BIRC5 was higher in stimulated cells.", "an experimental condition"),
]
OWN = [
    "BIRC5 was higher in tumours with elevated MYCN expression.",
    "BIRC5 was higher in MYCN-high samples than in MYCN-low samples.",
    "BIRC5 was higher in high-MYCN tumours.",
    "BIRC5 expression was increased in tumours with high MYCN mRNA levels.",
    "BIRC5 was 4-fold higher in MYCN-high versus MYCN-low tumours.",
    "BIRC5 was higher in MYCN-high tumours, many of which are MYCN-amplified.",
    "BIRC5 was higher in MYCN-high-expressing tumours.",
    "Compared with the remaining tumours, BIRC5 was higher in MYCN-high tumours.",
]


@pytest.fixture(scope="module")
def record() -> StudyRecord:
    result = StudyResult.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    return StudyRecord(study_id=result.study_id, result=result, lexicon=Lexicon.from_study(result))


@pytest.mark.parametrize(("text", "what"), OTHER, ids=[t[:50] for t, _ in OTHER])
def test_another_grouping_is_not_supported(record, text, what):
    (claim,) = audit_text(text, record).claims
    assert claim.verdict == "mismatch", claim.headline.plain
    groups = record.lexicon.groups(text)
    assert {g.what for g in groups if g.which == "other"} == {what}
    assert not [g for g in groups if g.which != "other"]


@pytest.mark.parametrize("text", OWN, ids=[t[:50] for t in OWN])
def test_the_studys_own_groups_in_other_words_stay_supported(record, text):
    (claim,) = audit_text(text, record).claims
    assert claim.verdict == "supported", claim.headline.plain
