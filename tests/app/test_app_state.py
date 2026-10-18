"""Task 9 gate: pure view-models for the app; every name and value is escaped."""

import pytest

from qpilot.app_state import (
    CANNOT_TELL,
    FOOTER,
    card_view,
    cards_in_order,
    confidence_badge,
    decision_counter,
    evidence_view,
    footer_lines,
    meter_html,
    meter_rows,
    next_card,
    policy_lines,
    results_table,
    review_body,
    review_head_line,
    study_summary,
)
from qpilot.core.vocabulary import banned_words
from qpilot.schemas import CardOption, ContrastResult, DecisionCard, Fact, Grade

HEADLINE = ["ODC1", "BIRC5", "NTRK1", "NM23A"]


def _row(view, option_id):
    return next(r for r in view.options if r.id == option_id)


def test_refset_card_view_shows_the_flip(fixture_cards, fixture_facts):
    view = card_view(fixture_cards[0], fixture_facts)
    assert view.title == "Which control genes to normalise to"
    assert view.needs_human and view.status == "open"
    recommended = dict((g, (fc, word)) for g, fc, word in _row(view, "recommended").cells)
    assert recommended["ODC1"] == ("3.6×", "up")
    hmbs = dict((g, (fc, word)) for g, fc, word in _row(view, "hmbs_alone").cells)
    assert hmbs["NM23A"] == ("1.6×", "no call")
    assert "3.6×" in view.html and "no call" in view.html and "ODC1" in view.html
    assert 'data-fact="f_n_flipped_refset"' in view.impact_html
    assert "a person makes it" in view.explanation_plain


def test_auto_decided_card_says_so_once(fixture_cards, fixture_facts):
    view = card_view(fixture_cards[2], fixture_facts)
    assert view.status == "auto_decided" and not view.needs_human
    assert view.status_line.count("Decided automatically") == 1
    assert _row(view, "drop").chosen and _row(view, "drop").recommended


def test_script_names_render_escaped(fixture_facts):
    evil = "<script>alert(1)</script>"
    result = ContrastResult(target=evil, log2fc=1.0, fc=2.0, ci=(1.5, 2.5), p=0.01, t=3.0,
                            n_hi=5, n_lo=5, conclusion="up")  # fmt: skip
    card = DecisionCard(
        id="card_x", kind="reference_set", rank=1, impact={"flips": True, "n_genes_flipped": 1},
        evidence={}, options=[CardOption(id="o1", label=evil, per_gene={evil: result})],
        recommended="o1", rationale_template="nope_v1", facts=[],
    )  # fmt: skip
    view = card_view(card, fixture_facts)
    assert "<script>" not in view.html
    assert view.html.count("&lt;script&gt;") == 2  # the label and the gene column
    badge = confidence_badge(Grade(level="Low", reasons=[evil], checks=[]))
    assert "<script>" not in badge and "&lt;script&gt;" in badge


def test_meter_rows_and_html(fixture_result):
    rows = {r.gene: r for r in meter_rows(fixture_result, HEADLINE)}
    assert list(rows) == HEADLINE
    assert rows["ODC1"].holds_text == "100%" and rows["ODC1"].level == "Moderate"
    assert rows["NM23A"].holds == fixture_result.robustness["NM23A"].holds
    assert rows["NM23A"].conclusion == "up" and rows["NM23A"].level == "Very low"
    markup = meter_html(fixture_result, HEADLINE)
    assert markup.count("qp-meter-row") == 4 and "fragile" in markup
    assert 'data-fact="f_holds_nm23a"' in markup and "186" in markup


def test_summary_and_rule(fixture_result):
    summary = study_summary(fixture_result)
    assert "64 plates" in summary.plain and "366 samples" in summary.plain
    assert summary.rule.startswith("up or down only if p < 0.05")
    assert 'data-fact="f_n_hi"' in summary.html


def test_confidence_badge_lists_reasons(fixture_result, fixture_facts):
    badge = confidence_badge(fixture_result.confidence["NM23A"], "NM23A", fixture_facts)
    assert "level-very_low" in badge
    assert badge.count("<li>") == len(fixture_result.confidence["NM23A"].reasons) == 3


def test_card_order_counter_and_next(fixture_cards):
    shuffled = list(reversed(fixture_cards))
    assert [c.id for c in cards_in_order(shuffled)] == [c.id for c in fixture_cards]
    assert next_card(shuffled).id == "card_refset"
    assert decision_counter(fixture_cards) == (
        "2 decisions could change a conclusion · 1 made automatically"
    )
    decided = [c.model_copy(update={"status": "decided"}) for c in fixture_cards]
    assert next_card(decided) is None


def test_results_table(fixture_result):
    table = results_table(fixture_result)
    assert len(table) == len(fixture_result.contrasts) == 58
    odc1 = table.set_index("Gene").loc["ODC1"]
    assert odc1["Fold change"] == "3.6×" and odc1["95 % CI"] == "2.4× – 5.3×"
    assert odc1["Conclusion"] == "up" and odc1["Confidence"] == "Moderate"


def test_policy_and_footer():
    lines = policy_lines()
    assert len(lines) == 3 and lines[2].startswith("Human only")
    footer = footer_lines("0.1.0", "fce7a44e8b47b90759c646b557de568f7af77e75")
    assert footer[: len(FOOTER)] == list(FOOTER)
    assert footer[-1] == "qPilot 0.1.0 · LinRegPCR (rdmlpython) @ fce7a44"


# ---------- Evidence Ledger panel and Run Review ----------


@pytest.fixture(scope="module")
def toy_ledger():
    from qpilot.qpcr.evidence import evidence_for
    from tests.engine.evidence_toys import toy_design, toy_model, toy_table

    table, design = toy_table(), toy_design()
    return evidence_for(table, toy_model(table, design), design)


def test_evidence_view_shows_a_chip_per_item_and_what_the_study_cannot_tell(toy_ledger):
    markup = evidence_view(toy_ledger)
    for status in ("present", "absent", "unknown", "not_applicable"):
        assert f"qp-ev-{status}" in markup
    assert markup.count('<span class="qp-ev ') == len(toy_ledger.items)
    cannot = markup.split(CANNOT_TELL, 1)[1].split("<details>", 1)[0]
    assert "No-RT control" in cannot and "genomic DNA carry-over cannot be checked" in cannot
    assert "Inter-run calibrator" not in cannot  # not applicable: listed under what it shows
    assert 'data-fact="f_ev_n_present"' in markup
    assert banned_words(markup) == []


def test_evidence_view_numbers_come_only_from_facts(toy_ledger):
    import html
    import re

    text = re.sub(r'<span class="fact"[^>]*>[^<]*</span>', "", evidence_view(toy_ledger))
    assert not re.search(r"\d", html.unescape(re.sub(r"<[^>]+>", "", text)))


def test_evidence_view_escapes_and_refuses_naked_numbers(toy_ledger):
    evil = '<img src=x onerror="alert(1)">'
    items = [i.model_copy(update={"title": evil}) for i in toy_ledger.items]
    items[0] = items[0].model_copy(update={"status": "<b>bad</b>"})
    items[1] = items[1].model_copy(
        update={"consequence": items[1].consequence.model_copy(update={"text": "42 wells"})}
    )
    facts = {**toy_ledger.facts, "f_ev_n_present": Fact(id="f_ev_n_present", value=evil)}
    ledger = toy_ledger.model_copy(update={"items": items, "facts": facts})
    markup = evidence_view(ledger)
    assert "<img" not in markup and "<b>bad" not in markup and "&lt;img" in markup
    assert "qp-ev-unknown" in markup  # an unknown status shows as unknown
    assert "42 wells" not in markup and "This line could not be shown." in markup


def test_evidence_view_without_a_ledger_says_why():
    markup = evidence_view(None, "the input file of this study is not <available>")
    assert "not available for this study: the input file of this study is not &lt;" in markup
    assert "<available>" not in markup
    assert evidence_view(None).endswith("not available for this study.</p></div>")


def test_review_body_keeps_only_the_main_part():
    page = "<!doctype html><html><head><style>body{}</style></head><body><main>\n<h1>R</h1>\n"
    assert review_body(page + "</main></body></html>") == "<h1>R</h1>"
    assert review_body("<p>no main</p>") == ""
    assert review_head_line(None) == ""
    assert "<code>abcdef0123456789</code>" in review_head_line("abcdef0123456789" * 4)
