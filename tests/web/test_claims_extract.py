"""The Claim Auditor's reader: many phrasings of qPCR results prose, read by rules alone.

The lexicon here is built from the demo study's own target names (as the file names them) and
its marker split; no study is loaded and no number below is data: every value is the one the
sentence itself writes, and each test checks that the reader found it and where.
"""

from __future__ import annotations

import math

import pytest

from qpilot.claims.extract import extract, sentences
from qpilot.claims.lexicon import Lexicon, marker_groups, named_groups

COMPARED = ["ODC1", "BIRC5", "NTRK1", "NM23A", "CD44", "AHCY", "DDC", "PRKACB_bis", "MAPT"]
REFERENCES = ["ALUsq(Eurogentec)", "HMBS", "HPRT1", "SDHA(1)", "UBC(2)"]


@pytest.fixture(scope="module")
def lex() -> Lexicon:
    a, b, a_words, b_words = marker_groups("MYCN")
    return Lexicon(
        compared=COMPARED,
        references=REFERENCES,
        marker="MYCN(4)",
        group_a=a,
        group_b=b,
        group_a_words=a_words,
        group_b_words=b_words,
    )


def gene_claims(text: str, lex: Lexicon) -> dict[str, object]:
    return {c.gene: c for c in extract(text, lex) if c.kind == "gene"}


def fold_range(claim) -> tuple[float, float]:  # noqa: ANN001
    """The fold change the words allow, as plain folds (inf for "more than")."""
    return 2**claim.fold.lo, (2**claim.fold.hi if math.isfinite(claim.fold.hi) else math.inf)


def spans(text: str, claim) -> dict[str, str]:  # noqa: ANN001
    return {m.role: text[m.span.start : m.span.end] for m in claim.marks}


# ---- genes ---------------------------------------------------------------------------------


def test_genes_by_name_assay_name_and_hgnc_alias(lex):
    text = (
        "Survivin was up-regulated, TrkA was down-regulated, PRKACB was higher and "
        "odc1 was increased."
    )
    claims = gene_claims(text, lex)
    assert set(claims) == {"BIRC5", "NTRK1", "PRKACB_bis", "ODC1"}
    assert claims["BIRC5"].gene_via == "alias" and claims["PRKACB_bis"].gene_via == "assay"
    assert claims["ODC1"].gene_via == "name"
    assert spans(text, claims["BIRC5"])["gene"] == "Survivin"


def test_a_gene_the_study_did_not_measure_is_found_and_marked(lex):
    (claim,) = extract("GAPDH was unchanged between the groups.", lex)
    assert claim.gene == "GAPDH" and claim.gene_status == "absent"


def test_control_and_marker_genes_are_marked(lex):
    claims = gene_claims("HMBS was lower in MYCN-high tumours, and MYCN was higher.", lex)
    assert claims["HMBS"].gene_status == "reference"
    assert claims["MYCN(4)"].gene_status == "marker"


def test_group_words_are_not_genes(lex):
    claims = gene_claims("ODC1 was higher in MYCN-high tumours than in MYCN-low tumours.", lex)
    assert set(claims) == {"ODC1"}


def test_words_that_are_hgnc_symbols_are_not_genes(lex):
    assert extract("We used a SET of primers and the MAX signal increased.", lex) == []


# ---- directions ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "direction"),
    [
        ("ODC1 was up-regulated.", "up"),
        ("ODC1 was upregulated.", "up"),
        ("ODC1 expression increased.", "up"),
        ("ODC1 was elevated.", "up"),
        ("ODC1 was overexpressed.", "up"),
        ("ODC1 was more highly expressed.", "up"),
        ("ODC1 was induced.", "up"),
        ("ODC1 was down-regulated.", "down"),
        ("ODC1 was reduced.", "down"),
        ("ODC1 expression decreased.", "down"),
        ("ODC1 was lower.", "down"),
        ("ODC1 was repressed.", "down"),
        ("ODC1 was unchanged.", "none"),
        ("ODC1 did not differ.", "none"),
        ("ODC1 showed no significant difference.", "none"),
        ("ODC1 levels were similar.", "none"),
        ("ODC1 was not increased.", "none"),
        ("ODC1 was not significantly up-regulated.", "none"),
        ("ODC1 did not change.", "none"),
    ],
)
def test_direction_words(lex, sentence, direction):
    (claim,) = extract(sentence, lex)
    assert claim.direction == direction


def test_negation_and_hedges_are_marked(lex):
    (claim,) = extract("ODC1 was not increased.", lex)
    assert claim.negated and claim.direction == "none"
    (claim,) = extract("ODC1 tended to be higher.", lex)
    assert claim.hedged and claim.direction == "up"
    assert spans("ODC1 tended to be higher.", claim)["hedge"] == "tended to"


def test_a_sentence_about_the_second_group_is_turned_around(lex):
    text = "BIRC5 was lower in MYCN-low tumours than in MYCN-high tumours."
    (claim,) = extract(text, lex)
    assert claim.direction == "down" and claim.inverted
    (claim,) = extract("BIRC5 was higher in MYCN-high tumours than in the rest.", lex)
    assert claim.direction == "up" and not claim.inverted
    (claim,) = extract("Compared with MYCN-high tumours, BIRC5 was higher in the rest.", lex)
    assert claim.inverted


# ---- fold values ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "written", "low", "high", "comparator"),
    [
        ("ODC1 was 3.6-fold higher.", "3.6-fold", 3.55, 3.65, "exact"),
        ("ODC1 was 3.6 fold higher.", "3.6 fold", 3.55, 3.65, "exact"),
        ("ODC1 was 3.6× higher.", "3.6×", 3.55, 3.65, "exact"),
        ("ODC1 was 3.6x higher.", "3.6x", 3.55, 3.65, "exact"),
        ("ODC1 was 3.6 times higher.", "3.6 times", 3.55, 3.65, "exact"),
        ("ODC1 was four-fold higher.", "four-fold", 3.5, 4.5, "exact"),
        ("ODC1 was twofold higher.", "twofold", 1.5, 2.5, "exact"),
        ("ODC1 was more than 3-fold higher.", "more than 3-fold", 3.0, math.inf, "at_least"),
        ("ODC1 was >3-fold higher.", ">3-fold", 3.0, math.inf, "at_least"),
        ("ODC1 was up to 3-fold higher.", "up to 3-fold", 1.0, 3.0, "at_most"),
        ("ODC1 was 2–3-fold higher.", "2–3-fold", 1.5, 3.5, "range"),
        ("ODC1 was increased (fold change = 3.6).", "fold change = 3.6", 3.55, 3.65, "exact"),
    ],
)
def test_fold_values(lex, sentence, written, low, high, comparator):
    (claim,) = extract(sentence, lex)
    assert claim.fold is not None and claim.fold.mark.written == written
    assert claim.fold.comparator == comparator
    lo, hi = fold_range(claim)
    assert lo == pytest.approx(low) and hi == pytest.approx(high)


def test_about_widens_the_written_range(lex):
    (claim,) = extract("ODC1 was about 3-fold higher.", lex)
    lo, hi = fold_range(claim)
    assert claim.fold.comparator == "about" and lo < 2.5 and hi > 3.5


def test_percent_changes_and_folds_below_one(lex):
    (claim,) = extract("We saw a 72 % decrease in DDC.", lex)
    assert claim.fold.kind == "percent" and claim.fold.sign == -1 and claim.direction == "down"
    lo, hi = fold_range(claim)  # a 72 % decrease is a fold of 0.28, i.e. 1/0.28 lower
    assert 1 / 0.285 == pytest.approx(lo) and 1 / 0.275 == pytest.approx(hi)
    (claim,) = extract("DDC was increased by 50 %.", lex)
    assert claim.fold.sign == 1 and fold_range(claim)[0] == pytest.approx(1.495)
    (claim,) = extract("DDC changed 0.28-fold.", lex)
    assert claim.fold.sign == -1


def test_log2_fold_changes(lex):
    (claim,) = extract("AHCY was reduced (log2 FC = -1.2).", lex)
    assert claim.fold.kind == "log2" and claim.fold.sign == -1
    assert claim.fold.lo == pytest.approx(1.15) and claim.fold.hi == pytest.approx(1.25)


def test_values_given_respectively(lex):
    text = "ODC1, BIRC5 and CD44 were up-regulated (3.6-, 4.0- and 2.5-fold, respectively)."
    claims = gene_claims(text, lex)
    assert [claims[g].fold.value for g in ("ODC1", "BIRC5", "CD44")] == [3.6, 4.0, 2.5]
    assert all(claims[g].direction == "up" for g in claims)


def test_a_list_shares_its_words(lex):
    claims = gene_claims("ODC1, BIRC5 and NTRK1 were significantly up-regulated.", lex)
    assert set(claims) == {"ODC1", "BIRC5", "NTRK1"}
    assert {c.direction for c in claims.values()} == {"up"}
    assert {c.significance for c in claims.values()} == {"significant"}
    claims = gene_claims("ODC1 was up-regulated, as was BIRC5.", lex)
    assert claims["BIRC5"].direction == "up"


def test_each_gene_keeps_its_own_words(lex):
    text = "ODC1 was 3-fold higher and BIRC5 was lower, whereas NM23A was unchanged."
    claims = gene_claims(text, lex)
    assert claims["ODC1"].direction == "up" and claims["ODC1"].fold.value == 3
    assert claims["BIRC5"].direction == "down" and claims["BIRC5"].fold is None
    assert claims["NM23A"].direction == "none"


# ---- p-values and significance -------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "op", "value", "adjusted"),
    [
        ("ODC1 was higher (p < 0.01).", "<", 0.01, False),
        ("ODC1 was higher (P<0.001).", "<", 0.001, False),
        ("ODC1 was higher (p ≤ 0.05).", "<=", 0.05, False),
        ("ODC1 was higher (p = 0.003).", "=", 0.003, False),
        ("ODC1 was higher (p<.05).", "<", 0.05, False),
        ("ODC1 was higher (P = 2.1 × 10−8).", "=", 2.1e-8, False),
        ("ODC1 was higher (p = 2.1e-8).", "=", 2.1e-8, False),
        ("ODC1 was higher (P < 10^-6).", "<", 1e-6, False),
        ("ODC1 was higher (q < 0.05).", "<", 0.05, True),
        ("ODC1 was higher (FDR < 0.01).", "<", 0.01, True),
    ],
)
def test_p_values(lex, sentence, op, value, adjusted):
    (claim,) = extract(sentence, lex)
    assert claim.p is not None and claim.p.op == op and claim.p.adjusted is adjusted
    assert claim.p.value == pytest.approx(value)
    written = sentence[claim.p.mark.span.start : claim.p.mark.span.end]
    assert written == claim.p.mark.written and written[0] in "pPqF" and ")" not in written


def test_significance_words(lex):
    (claim,) = extract("ODC1 was significantly higher.", lex)
    assert claim.significance == "significant"
    (claim,) = extract("ODC1 was higher, but this was not significant.", lex)
    assert claim.significance == "not_significant"
    text = "PRKACB tended to be higher in the rest, although this did not reach significance."
    (claim,) = extract(text, lex)
    assert claim.significance == "not_significant" and claim.hedged and claim.inverted


def test_a_semicolon_inside_parentheses_does_not_split(lex):
    (claim,) = extract("AHCY was not significantly increased (log2 FC = 0.4; q = 0.2).", lex)
    assert claim.fold is not None and claim.p is not None and claim.p.adjusted


# ---- robustness, normaliser, n, efficiency -------------------------------------------------


@pytest.mark.parametrize(
    "words",
    ["robustly", "consistently", "reproducibly", "regardless of the reference genes"],
)
def test_robustness_words(lex, words):
    (claim,) = extract(f"ODC1 was {words} up-regulated.", lex)
    assert claim.robust


def test_consistent_with_is_not_a_robustness_word(lex):
    (claim,) = extract("ODC1 was up-regulated, consistent with earlier reports.", lex)
    assert not claim.robust


def test_normalisers(lex):
    text = "Expression was normalised to the geometric mean of HMBS and SDHA."
    (claim,) = extract(text, lex)
    assert claim.kind == "normaliser" and claim.normaliser == ("HMBS", "SDHA(1)")
    claims = extract("Using GAPDH as reference, CD44 was lower.", lex)
    norm = next(c for c in claims if c.kind == "normaliser")
    gene = next(c for c in claims if c.kind == "gene")
    assert norm.normaliser == ("GAPDH",) and gene.gene == "CD44" and gene.normaliser == ("GAPDH",)


def test_a_normaliser_in_parentheses_belongs_to_its_gene(lex):
    text = "ODC1 was 4.7-fold higher (normalised to UBC) and NM23A was up-regulated."
    claims = gene_claims(text, lex)
    assert claims["ODC1"].normaliser == ("UBC(2)",) and claims["NM23A"].normaliser == ()


def test_a_normaliser_stated_once_applies_to_the_text(lex):
    claims = extract("Data were normalized to HPRT1. ODC1 was higher.", lex)
    gene = next(c for c in claims if c.kind == "gene")
    assert gene.normaliser == ("HPRT1",)


def test_group_sizes(lex):
    (claim,) = extract("n = 53 vs 294.", lex)
    assert claim.kind == "n" and claim.n_values == (53, 294)
    (claim,) = extract("We compared 53 vs 294 tumours.", lex)
    assert claim.n_values == (53, 294)


def test_efficiency_ranges(lex):
    (claim,) = extract("All assays had efficiencies of 90–110 %.", lex)
    assert claim.kind == "efficiency" and claim.efficiency == pytest.approx((89.5, 110.5))
    (claim,) = extract("PCR efficiency was between 1.9 and 2.1 for ODC1.", lex)
    assert claim.efficiency == pytest.approx((85.0, 115.0)) and claim.genes == ("ODC1",)
    (claim,) = extract("Efficiencies were above 95 %.", lex)
    assert claim.efficiency[0] == pytest.approx(94.5) and math.isinf(claim.efficiency[1])


# ---- text --------------------------------------------------------------------------------


def test_sentences_do_not_end_at_abbreviations_or_decimals(lex):
    text = "ODC1 was 3.6-fold higher vs. the rest (Fig. 2). BIRC5 was lower, e.g. in tumours."
    assert len(sentences(text)) == 2


def test_spans_point_into_the_text(lex):
    text = "In MYCN-high tumours, ODC1 was 3.6-fold up-regulated (p < 0.01)."
    (claim,) = extract(text, lex)
    found = spans(text, claim)
    assert found == {
        "group": "MYCN-high",
        "gene": "ODC1",
        "fold": "3.6-fold",
        "direction": "up-regulated",
        "p": "p < 0.01",
    }


def test_no_claim_without_a_gene_or_without_a_claim(lex):
    assert extract("Total RNA was extracted with TRIzol.", lex) == []
    assert extract("We measured ODC1, BIRC5 and NTRK1 in every sample.", lex) == []


def test_named_groups_are_whole_words():
    a_words, b_words = named_groups("KO", "WT")
    lex = Lexicon(
        compared=["1-Mar"], group_a="KO", group_b="WT", group_a_words=a_words,
        group_b_words=b_words,
    )  # fmt: skip
    (claim,) = extract("1-Mar was lower in WT than in KO mice.", lex)
    assert claim.gene == "1-Mar" and claim.direction == "down" and claim.inverted
    assert claim.fold is None
