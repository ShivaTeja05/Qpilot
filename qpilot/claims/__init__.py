"""The Claim Auditor: read the claims in a results paragraph and check each against the study.

Reviewers and PIs read sentences like "ODC1 was 3.6-fold up-regulated in MYCN-high tumours
(p < 0.01)". This package reads such prose **deterministically** (:mod:`qpilot.claims.extract`),
checks every claim against the study's own record (the stored result, qPilot's choice grid and,
when there is one, the robustness audit) in :mod:`qpilot.claims.check`, and writes example
sentences from the study's facts (:mod:`qpilot.claims.examples`).

The trust contract (``qPilot-AI-USE-CASES.md``, "Claim Auditor"):

* the extraction is shown, span by span, before any verdict is believed;
* verdicts come from a fixed vocabulary and from the engine only, never from a model;
* every number in a reason is a fact with an id and a source (the study's facts, the grid, the
  audit, or the reader's own text, quoted); the reasons pass the "no naked numbers" validator;
* an optional model may only *propose* a reading (:mod:`qpilot.claims.assist`), and every value
  it proposes must appear verbatim in the sentence it cites.
"""

from qpilot.claims.check import StudyRecord, audit_text, record_of
from qpilot.claims.extract import Claim, extract
from qpilot.claims.lexicon import Lexicon
from qpilot.claims.models import ClaimsReport

__all__ = ["Claim", "ClaimsReport", "Lexicon", "StudyRecord", "audit_text", "extract", "record_of"]
