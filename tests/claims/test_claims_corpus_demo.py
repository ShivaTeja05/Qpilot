"""The claim corpus on the real demo study, with its choice grid, over the API.

The same sentences as ``test_claims_corpus.py``; the grid can only turn a claim that does not
hold in the planned analysis into "holds only under some choices" (``grid: False`` entries and
claims about another set of control genes), never change a supported claim, a different
grouping or a gene the study cannot answer about.
"""

from __future__ import annotations

import pytest

from tests.claims.corpus import CORPUS
from tests.web.test_claims_demo import check, demo, demo_study  # noqa: F401 (fixtures)

pytestmark = pytest.mark.demo_data


def test_the_corpus_on_the_demo_study(demo):  # noqa: F811
    wrong = []
    for entry in CORPUS:
        claims = check(demo, entry["text"])
        got = [c["verdict"] for c in claims]
        expected = entry["verdicts"]
        ok = len(got) == len(expected)
        for claim, want, have in zip(claims, expected, got, strict=False):
            allowed = {want}
            if entry.get("grid") is False or claim["kind"] == "normaliser":
                allowed.add("choices")
            ok = ok and have in allowed
        if not ok:
            wrong.append((entry["text"], expected, got))
    assert not wrong, wrong


def test_the_walk_sentence(demo):  # noqa: F811
    """The sentence a hands-on walk found marked Supported, with its p on MYCN(4)."""
    text = (
        "Survivin was 4-fold higher in MYCN-amplified tumours (p < 0.001). Expression was "
        "normalised to GAPDH and B2M."
    )
    gene, norm = check(demo, text)
    assert gene["gene"] == "BIRC5" and gene["verdict"] == "mismatch"
    assert "not MYCN amplification" in gene["headline"]["plain"]
    assert gene["reading"]["p_written"] == "p < 0.001"
    assert gene["reading"]["normaliser_scope"] == "text"
    assert norm["kind"] == "normaliser" and norm["verdict"] == "contradicted"
