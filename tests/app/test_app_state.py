"""Task 9 gate: pure view-models for the app; every name and value is escaped."""

from qpilot.app_state import (
    FOOTER,
    card_view,
    cards_in_order,
    confidence_badge,
    decision_counter,
    footer_lines,
    meter_html,
    meter_rows,
    next_card,
    policy_lines,
    results_table,
    study_summary,
)
from qpilot.schemas import CardOption, ContrastResult, DecisionCard, Grade

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
