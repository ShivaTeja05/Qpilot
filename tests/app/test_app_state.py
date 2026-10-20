"""The view-models the one page builds on (qpilot/app_state.py); every name is escaped."""

from qpilot.app_state import (
    FOOTER,
    card_view,
    cards_in_order,
    decision_counter,
    design_line,
    next_card,
    study_summary,
)
from qpilot.schemas import CardOption, ContrastResult, DecisionCard


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
