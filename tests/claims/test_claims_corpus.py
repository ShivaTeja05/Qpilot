"""The Claim Auditor on a corpus of tricky sentences (``tests/claims/corpus.py``).

Each sentence is checked against the demo study's record as the contract fixture holds it
(``tests/fixtures/results.json``: no choice grid, no audit), so this runs without the 7 MB
download; ``test_claims_corpus_demo.py`` runs the same corpus on the real study with its grid.
Besides each verdict, the tests check what the verdict rests on: a claim about groups the study
does not compare says what it compares instead; a p-value belongs to the gene whose claim it
closes; a normaliser sentence applies only to the claims it is about, and the claim says where
its normaliser was read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qpilot.claims import StudyRecord, audit_text
from qpilot.claims.lexicon import Lexicon, find_genes
from qpilot.schemas import StudyResult
from tests.claims.corpus import CORPUS

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "results.json"


@pytest.fixture(scope="module")
def record() -> StudyRecord:
    result = StudyResult.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    return StudyRecord(study_id=result.study_id, result=result, lexicon=Lexicon.from_study(result))


def test_the_corpus_is_large_enough():
    assert len(CORPUS) >= 30
    assert sum(len(e["verdicts"]) for e in CORPUS) >= 40


@pytest.mark.parametrize("entry", CORPUS, ids=[e["text"][:60] for e in CORPUS])
def test_each_sentence_gets_the_verdict_the_record_supports(record, entry):
    report = audit_text(entry["text"], record)
    got = [c.verdict for c in report.claims]
    assert got == entry["verdicts"], [(c.gene, c.verdict, c.headline.plain) for c in report.claims]
    genes = {c.gene: c for c in report.claims if c.kind == "gene"}
    if "p" in entry:
        with_p = [c.gene for c in report.claims if c.reading.p_written]
        assert with_p == [entry["p"]], with_p
    for gene, refs in entry.get("normaliser", {}).items():
        assert tuple(genes[gene].reading.normaliser) == refs, gene
    for gene, scope in entry.get("scope", {}).items():
        assert genes[gene].reading.normaliser_scope == scope, gene


def test_a_different_grouping_says_what_the_study_compares(record):
    text = "Survivin was 4-fold higher in MYCN-amplified tumours (p < 0.001)."
    (claim,) = audit_text(text, record).claims
    assert claim.gene == "BIRC5" and claim.reading.gene_via == "alias"
    assert claim.verdict == "mismatch"
    assert claim.verdict_label == "Not supported: different groups"
    plain = claim.headline.plain
    assert "compares MYCN-high against MYCN-low expression" in plain
    assert "not MYCN amplification" in plain and "“MYCN-amplified”" in plain
    assert claim.reading.other_groups == ["MYCN-amplified"]
    assert claim.reading.p_written == "p < 0.001"  # survivin's, not "MYCN(4)"'s
    assert [c.check for c in claim.checks] == ["groups"]
    # the sentence the record supports, for the study's own groups
    assert claim.suggestion is not None
    assert claim.suggestion.plain.startswith("BIRC5 was higher in the MYCN-high group")
    assert "MYCN-amplified" in {f.text for f in claim.headline.facts}  # quoted, as a fact


def test_mismatch_is_ranked_with_the_serious_verdicts(record):
    text = (
        "Survivin was higher in MYCN-amplified tumours. NTRK1 was higher in MYCN-high tumours. "
        "NM23A was robustly up-regulated in MYCN-high tumours."
    )
    report = audit_text(text, record)
    by = {c.verdict: c.severity for c in report.claims}
    assert by["contradicted"] > by["mismatch"] > by["overstated"]
    assert report.summary.counts["mismatch"] == 1
    assert report.verdicts["mismatch"] and report.verdict_rules["mismatch"]


def test_a_global_normaliser_says_it_was_read_from_another_sentence(record):
    text = "ODC1 was higher in MYCN-high tumours. Expression was normalised to GAPDH and B2M."
    gene, norm = audit_text(text, record).claims
    assert norm.kind == "normaliser" and norm.verdict == "contradicted"
    line = next(c for c in gene.checks if c.check == "normaliser").text.plain
    assert line.startswith("Your text states once, for all the data, how it was normalised")
    assert "“Expression was normalised to GAPDH and B2M.”" in line
    assert "normalised to GAPDH and B2M (stated once for all the data)" in gene.reading.words


def test_a_normaliser_that_names_no_claim_is_given_to_none(record):
    text = "ODC1 was higher in MYCN-high tumours. GAPDH served as a reference gene."
    claims = audit_text(text, record).claims
    gene = next(c for c in claims if c.kind == "gene")
    assert gene.reading.normaliser == []


def test_every_number_in_a_mismatch_is_a_fact(record):
    (claim,) = audit_text("NTRK1 was lower in stage 4 tumours.", record).claims
    assert claim.verdict == "mismatch"
    cited = {f.id for f in claim.headline.facts}
    assert all(seg.fact in cited for seg in claim.headline.segments if seg.fact)
    plain_digits = [s.text for s in claim.headline.segments if s.fact is None and any(
        ch.isdigit() for ch in s.text
    )]  # fmt: skip
    assert plain_digits == []


# ---- the one gene-name resolver (Claim Auditor and Ask) ---------------------------------------


@pytest.mark.parametrize(
    ("text", "gene", "via"),
    [
        ("Is survivin really higher?", "BIRC5", "alias"),
        ("what about TrkA", "NTRK1", "alias"),
        ("is prkacb robust", "PRKACB_bis", "assay"),
        ("ubc as the control", "UBC(2)", "assay"),
        ("ODC1?", "ODC1", "name"),
    ],
)
def test_find_genes_resolves_names_assay_names_and_aliases(text, gene, via):
    genes = ["BIRC5", "NTRK1", "PRKACB_bis", "UBC(2)", "ODC1"]
    (found,) = find_genes(text, genes)
    assert (found.gene, found.via) == (gene, via)
    assert text[found.start : found.end] == found.written


def test_find_genes_ignores_words_and_genes_not_given():
    assert find_genes("Is the KO higher than the WT in all samples?", ["BIRC5", "ODC1"]) == []
    assert find_genes("survivin", ["ODC1"]) == []
