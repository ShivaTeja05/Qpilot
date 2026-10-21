"""The view-models the one page builds on (qpilot/app_state.py); every name is escaped."""

import pytest

from qpilot.app_state import (
    FOOTER,
    card_label,
    card_view,
    cards_in_order,
    decision_counter,
    design_line,
    next_card,
    results_table,
    study_summary,
)
from qpilot.schemas import CardOption, ContrastResult, DecisionCard, Fact


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


def test_summary_and_rule(fixture_result):
    summary = study_summary(fixture_result)
    assert "64 plates" in summary.plain and "366 samples" in summary.plain
    assert summary.rule.startswith("up or down only if p < 0.05")
    assert 'data-fact="f_n_hi"' in summary.html


def test_card_order_counter_and_next(fixture_cards):
    shuffled = list(reversed(fixture_cards))
    assert [c.id for c in cards_in_order(shuffled)] == [c.id for c in fixture_cards]
    assert next_card(shuffled).id == "card_refset"
    assert decision_counter(fixture_cards) == (
        "2 decisions could change a conclusion · 1 made automatically"
    )
    decided = [c.model_copy(update={"status": "decided"}) for c in fixture_cards]
    assert next_card(decided) is None


def test_the_never_does_lines_and_the_design_sentence(fixture_result):
    assert FOOTER[0] == "For research use only. Not for clinical or diagnostic use."
    assert "wait for a person" in FOOTER[1]
    assert design_line(fixture_result).endswith("Expression-defined, not a clinical call.")


def test_results_table(fixture_result):
    table = results_table(fixture_result)
    assert len(table) == len(fixture_result.contrasts) == 58
    odc1 = table.set_index("Gene").loc["ODC1"]
    assert odc1["Fold change"] == "3.6×" and odc1["95 % CI"] == "2.4× – 5.3×"
    assert odc1["Conclusion"] == "up" and odc1["Confidence"] == "Moderate"


# ---------- Trace cards (opened on demand, decided like the analysis's cards) ----------

EVIL = '<img src=x onerror="alert(1)">'


@pytest.fixture(scope="module")
def toy_trace():
    from qpilot.qpcr import trace as T
    from tests.app.trace_toys import GENE, toy_trace_table
    from tests.engine.test_trace import context

    ctx = context(toy_trace_table(sample_name=EVIL))
    return ctx, T.trace_gene(ctx, GENE, top=3)


def test_trace_cell_names_the_top_place(toy_trace):
    from qpilot.app_state import TRACE_NOTHING, trace_cell

    _, result = toy_trace
    assert trace_cell(result).endswith(": changes the call")
    assert trace_cell(result).startswith("R1_20260101/") and f"({EVIL})" in trace_cell(result)
    empty = result.model_copy(update={"places": []})
    assert trace_cell(empty) == TRACE_NOTHING


def test_a_trace_card_shows_its_place_and_only_the_calls_it_changes(toy_trace, fixture_facts):
    _, result = toy_trace
    card = result.card(1)
    view = card_view(card, fixture_facts)
    assert view.title == "What to do with one unusual well"
    assert view.needs_human
    assert view.status_line == "Your decision: this choice can change a conclusion."
    assert view.genes == tuple(card.impact["flipped_genes"]) == ("DOWN",)
    assert "Can change a conclusion: the call of DOWN" in view.impact_html
    assert "<img" not in view.html and "&lt;img" in view.html and "What to check:" in view.html
    assert "Trace found this place unusual" in view.explanation_plain
    assert [r.id for r in view.options] == ["keep", "read_from_other_refs", "set_aside"]
    keep = dict((g, fc) for g, fc, _ in _row(view, "keep").cells)
    assert keep["DOWN"] == f"{card.options[0].per_gene['DOWN'].fc:.2g}×"
    fact = Fact(id="f_fc_down_recommended", value=0.123, fmt="{:.1f}", unit="×")
    shown = card_view(card, {**fixture_facts, fact.id: fact})  # keep reads the study's own facts
    assert dict((g, fc) for g, fc, _ in _row(shown, "keep").cells)["DOWN"] == "0.1×"
    label = card_label(card)
    assert label.startswith("Trace: sample ") and label.endswith("(open)")
    assert "&lt;img" not in label  # plain text: Gradio escapes a dropdown label itself


def test_trace_cards_come_after_the_analysis_cards(toy_trace, fixture_cards):
    _, result = toy_trace
    card = result.card(1)
    ordered = cards_in_order([card, *fixture_cards])
    assert ordered[-1] is card and [c.id for c in ordered[:-1]] == [c.id for c in fixture_cards]
    assert next_card([card, *fixture_cards]).id == "card_refset"
