"""Example sentences about a study, written from its own facts, so the auditor can be tried at once.

Nothing here is hand-written data: each sentence is a fixed English frame filled with the study's
genes, groups and numbers (rendered from its facts and the grid), and each is kept only if the
auditor's verdict on it is the one the frame was written to show. The frames are the kinds of
errors reviewers catch (``qPilot-AI-USE-CASES.md``, Claim Auditor):

* a true sentence about the lead gene (its fold and p, as the record has them);
* "robustly" for a call that holds in fewer than 80 % of the analyses qPilot checks;
* "did not differ" for a gene whose call one common choice removes (holds only under it);
* a fold larger than any analysis gives;
* a common control gene the study never measured named as the normaliser;
* an efficiency range some assays fall outside.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from qpilot.claims.check import StudyRecord, audit_text
from qpilot.claims.models import ClaimExample, ClaimExamples, Verdict
from qpilot.qpcr.confidence_checks import HOLDS_MIN

COMMON_CONTROLS = ("GAPDH", "ACTB", "B2M", "RPLP0", "TBP", "YWHAZ", "18S")


def _two(x: float) -> str:
    """A fold as a paper writes it: two significant digits (``3.3``, ``15``)."""
    return f"{float(f'{x:.2g}'):g}"


def _p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {_two(p)}"


def _fold_words(fc: float) -> tuple[str, str]:
    """``3.3-fold``, ``higher`` (or the inverse fold and ``lower`` for a decrease)."""
    if fc >= 1:
        return f"{_two(fc)}-fold", "higher"
    return f"{_two(1 / fc)}-fold", "lower"


def write_examples(record: StudyRecord, headline: list[str]) -> ClaimExamples:
    """Example sentences for this study, each verified to get the verdict it was written for."""
    result = record.result
    a, b = record.phrases
    contrasts = result.contrasts
    robust = result.robustness
    called = [g for g in contrasts if contrasts[g].conclusion in ("up", "down")]
    order = [g for g in headline if g in contrasts] + [g for g in called if g not in headline]
    a_in = a  # "higher in the MYCN-high group" (StudyRecord.phrases)

    def called_robust(gene: str, strong: bool) -> bool:
        c, r = contrasts[gene], robust.get(gene)
        return c.conclusion in ("up", "down") and r is not None and (r.holds >= HOLDS_MIN) == strong

    def true_lead(gene: str) -> str | None:
        c = contrasts[gene]
        if not called_robust(gene, True):
            return None
        fold, word = _fold_words(c.fc)
        return f"{gene} was {fold} {word} in {a_in} than in {b} ({_p(c.p)})."

    def robustly(gene: str) -> str | None:
        if not called_robust(gene, False):
            return None
        return f"{gene} was robustly {contrasts[gene].conclusion}-regulated in {a_in}."

    def one_choice(gene: str) -> str | None:
        if record.grid is None or contrasts[gene].conclusion == "none":
            return None
        from qpilot.web.results_views import IDX

        grid = record.grid
        for dim in grid.dimensions:
            rows = grid.one_at_a_time(dim)
            rows = rows[(rows["item"] == gene) & (rows[dim + IDX] != grid.planned[dim])]
            if (rows["conclusion"].astype(str) == "none").any():
                return f"{gene} did not differ between {a_in} and {b}."
        return None

    def too_large(gene: str) -> str | None:
        c = contrasts[gene]
        if c.conclusion not in ("up", "down"):
            return None
        far = c.ci[1] if c.conclusion == "up" else 1 / c.ci[0]  # the interval's far end
        word = "higher" if c.conclusion == "up" else "lower"
        return f"{gene} was {math.ceil(far * 2)}-fold {word} in {a_in} than in {b}."

    def missing_control(_: str) -> str | None:
        for name in COMMON_CONTROLS:
            if record.lexicon.status(name) == "absent" and name not in contrasts:
                return f"Expression was normalised to {name}."
        return None

    def efficiency(_: str) -> str | None:
        eff = result.efficiency
        if eff and any(not 0.9 <= e - 1 <= 1.1 for e in eff.values()):
            return "All assays had efficiencies of 90–110 %."
        return None

    frames: list[tuple[Verdict, str, Callable[[str], str | None], bool]] = [
        ("supported", "A true sentence: the lead gene's fold and p as the record has them.",
         true_lead, True),
        ("overstated", "“Robustly” for a call that holds in fewer than 80 % of the analyses "
         "qPilot checks.", robustly, True),
        ("choices", "“Did not differ” for a gene whose call one common choice removes.",
         one_choice, True),
        ("overstated", "A fold larger than any analysis of this study gives.", too_large, True),
        ("contradicted", "A common control gene this study never measured.", missing_control,
         False),
        ("contradicted", "An efficiency range some of the assays fall outside.", efficiency,
         False),
    ]  # fmt: skip
    kept: list[ClaimExample] = []
    used: set[str] = set()
    for intent, what, write, per_gene in frames:
        for gene in [g for g in order if g not in used] if per_gene else [""]:
            sentence = write(gene)
            if not sentence:
                continue
            report = audit_text(sentence, record)
            if report.claims and {c.verdict for c in report.claims} == {intent}:
                kept.append(ClaimExample(text=sentence, intent=intent, what=what))
                used.add(gene)
                break
    paragraph = " ".join(e.text for e in kept)
    return ClaimExamples(
        study_id=record.study_id,
        paragraph=paragraph,
        examples=kept,
        note=(
            "Written by qPilot from this study's own record (its genes, groups and numbers), "
            "not by a person or a model; each sentence was checked to come out as described."
        ),
    )
