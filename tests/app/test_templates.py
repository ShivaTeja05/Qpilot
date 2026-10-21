"""Task 9 gate: every template renders from facts with zero naked numbers and known ids only."""

import pytest

from qpilot.ai.client import ModelClient
from qpilot.ai.explain import card_names, explain_card
from qpilot.cli import main
from qpilot.core.validator import names_from_result, validate
from qpilot.explain.templates import TEMPLATES, TemplateError, render_template
from qpilot.schemas import Fact

CARD_TEMPLATES = ("refset_v1", "cutoff_v1", "undetermined_auto_v1", "undetermined_v1")


def test_every_template_renders_with_zero_naked_numbers(fixture_result):
    facts, names = fixture_result.facts, names_from_result(fixture_result)
    for key in TEMPLATES:
        genes = list(fixture_result.confidence) if key == "confidence_v1" else [None]
        for gene in genes:
            rendered = render_template(key, facts, gene=gene)
            check = validate(rendered.tokens, facts, names)
            assert check.ok, (key, gene, check.error())
            assert "{{" not in rendered.plain and "{{" not in rendered.html
            assert set(rendered.fact_ids) <= set(facts)


def test_card_templates_pass_the_model_layer_fallback(fixture_cards, fixture_facts):
    """Dev 2's explain_card validates the template with only the card's own names allowed."""
    for card in fixture_cards:
        rendered = render_template(card.rationale_template, fixture_facts, card=card)
        assert validate(rendered.tokens, fixture_facts, card_names(card)).ok, card.id
        explanation = explain_card(card, fixture_facts, client=ModelClient())
        assert explanation.fallback and explanation.validated
        assert explanation.tokens == render_template(card.rationale_template, fixture_facts).tokens


def test_refset_explanation_says_who_decides(fixture_facts):
    text = render_template("refset_v1", fixture_facts).plain
    assert "31 genes out of 58 change their conclusion" in text
    assert "a person makes it" in text
    assert "ODC1 3.6× vs 4.7×" in text  # recommended set vs the least stable gene alone


def test_zero_flips_is_said_in_words(fixture_facts):
    text = render_template("undetermined_auto_v1", fixture_facts).plain
    assert "No gene changes its conclusion" in text and "decided automatically" in text
    assert "0 of" not in text


def test_html_marks_every_number_with_its_fact(fixture_facts):
    rendered = render_template("summary_v1", fixture_facts)
    for fid in rendered.fact_ids:
        assert f'data-fact="{fid}"' in rendered.html
    assert rendered.html.count("<span") == len(rendered.fact_ids)


def test_confidence_phrasing_follows_fragility(fixture_facts):
    odc1 = render_template("confidence_v1", fixture_facts, gene="ODC1").plain
    nm23a = render_template("confidence_v1", fixture_facts, gene="NM23A").plain
    assert "no combination of the choices qPilot checks flips it" in odc1
    assert "a single choice can flip it" in nm23a and "Very low" in nm23a


def test_errors_are_explicit(fixture_facts):
    with pytest.raises(KeyError, match="unknown template"):
        render_template("nope_v1", fixture_facts)
    with pytest.raises(TemplateError, match="needs gene"):
        render_template("confidence_v1", fixture_facts)
    missing = {k: v for k, v in fixture_facts.items() if k != "f_n_genes"}
    with pytest.raises(TemplateError, match="f_n_genes"):
        render_template("meter_v1", missing)


def test_values_are_escaped_in_html(fixture_facts):
    facts = dict(fixture_facts)
    facts["f_order_1"] = Fact(id="f_order_1", value="<script>alert(1)</script>")
    rendered = render_template("refset_v1", facts)
    assert "<script>" not in rendered.html and "&lt;script&gt;" in rendered.html


def test_cli_explain_lists_and_renders(fixtures_dir, capsys):
    assert main(["explain"]) == 0
    assert "refset_v1" in capsys.readouterr().out
    results = str(fixtures_dir / "results.json")
    assert main(["explain", "meter_v1", "--results", results]) == 0
    assert "the 186 analyses qPilot checks" in capsys.readouterr().out
    assert main(["explain", "meter_v1", "--results", results, "--tokens"]) == 0
    assert "{{f_n_cells}}" in capsys.readouterr().out
    assert main(["explain", "confidence_v1", "--results", results]) == 1


FEATURE_TEMPLATES = ("evidence_v1", "grt_v1", "runreview_v1", "instrument_gate_v1",
                     "lookback_v1", "position_v1")  # fmt: skip


def test_feature_templates_are_registered_and_digit_free_without_their_facts(fixture_result):
    import re

    for key in FEATURE_TEMPLATES:
        assert key in TEMPLATES
        rendered = render_template(key, fixture_result.facts)
        assert rendered.plain and not re.search(r"\d", rendered.plain), key
        assert rendered.fact_ids == ()


def test_the_evidence_template_renders_a_ledger_through_the_registry():
    from qpilot.explain.evidence_text import render_evidence
    from qpilot.qpcr.evidence import evidence_for
    from tests.engine.evidence_toys import toy_design, toy_model, toy_table

    table, design = toy_table(), toy_design()
    ledger = evidence_for(table, toy_model(table, design), design)
    rendered = render_template("evidence_v1", ledger.facts)
    assert rendered.tokens == render_evidence(ledger).tokens
    assert "f_ev_n_present" in rendered.fact_ids and "No-RT control: absent." in rendered.plain


def test_structured_templates_point_to_their_renderer(fixture_facts):
    cases = {
        "instrument_gate_v1": ("f_instr_run_run_state", "render_gate"),
        "lookback_v1": ("f_lookback_instrument", "lookback_tokens"),
        "position_v1": ("f_position_base_rate", "position_tokens"),
    }
    for key, (fid, renderer) in cases.items():
        facts = {**fixture_facts, fid: Fact(id=fid, value="x")}
        with pytest.raises(TemplateError, match=renderer):
            render_template(key, facts)


ENGINE_TEMPLATES = ("trace_v1", "trace_set_aside_v1", "sheetcheck_v1", "sheetcheck_findings_v1",
                    "sheetcheck_handover_v1")  # fmt: skip


def test_trace_and_sheetcheck_templates_are_registered_and_digit_free(fixture_result):
    import re

    from qpilot.core.vocabulary import banned_words

    names = names_from_result(fixture_result)
    for key in ENGINE_TEMPLATES:
        assert key in TEMPLATES
        for gene in (None, "ODC1"):
            rendered = render_template(key, fixture_result.facts, gene=gene)
            assert rendered.plain and not re.search(r"\d", rendered.plain.replace("ODC1", ""))
            assert rendered.fact_ids == () and banned_words(rendered.plain, names) == []


@pytest.fixture(scope="module")
def toy_trace():
    from qpilot.qpcr import trace as T
    from tests.app.trace_toys import GENE, toy_trace_table
    from tests.engine.test_trace import context

    ctx = context(toy_trace_table())
    return ctx, T.trace_gene(ctx, GENE, top=3)


def test_the_trace_template_renders_a_gene_panel_through_the_registry(toy_trace):
    from qpilot.explain.trace_text import render_trace

    ctx, result = toy_trace
    rendered = render_template("trace_v1", result.facts, gene="DOWN", allowed_names=ctx.items)
    assert rendered.tokens == render_trace(result, allowed_names=ctx.items).tokens
    assert "Where to look first:" in rendered.plain and "f_trace_down_1_sample" in rendered.fact_ids


def test_the_sheetcheck_template_renders_a_check_through_the_registry(tmp_path):
    from qpilot.explain.sheetcheck_text import render
    from qpilot.qpcr.sheetcheck import check_sheet
    from tests.engine.test_sheetcheck import _slip_sheets, synthetic, wide_table, write_csv

    study = synthetic()
    columns, summaries, kwargs = _slip_sheets(study)["sign_inverted"]
    path = write_csv(tmp_path / "slip.csv", *wide_table(study, columns, summaries))
    result = check_sheet(path, **kwargs)
    for key in ("sheetcheck_v1", "sheetcheck_findings_v1"):
        rendered = render_template(key, result.facts)
        assert rendered.tokens == render(result, key).tokens
    assert (
        "The first place to look is column" in render_template("sheetcheck_v1", result.facts).plain
    )


def test_explain_card_works_on_a_trace_card(toy_trace, fixture_facts):
    from qpilot.ai.client import MockBackend
    from qpilot.explain.trace_text import CARD_TEXT

    _, result = toy_trace
    card = result.card(1)
    assert card.kind == "trace_set_aside" and card.rationale_template == "trace_set_aside_v1"
    explained = explain_card(card, fixture_facts, client=ModelClient())  # no model: the template
    assert explained.fallback and explained.validated and explained.tokens == CARD_TEXT
    reply = "Keep the well, or set the sample aside; a person decides, and it is logged."
    explained = explain_card(card, fixture_facts, client=ModelClient(MockBackend([reply])))
    assert not explained.fallback and explained.validated and explained.tokens == reply
    naked = ModelClient(MockBackend(["Set aside sample s12, it is 8 cycles late."]))
    explained = explain_card(card, fixture_facts, client=naked)  # a naked number: the template
    assert explained.fallback and explained.validated and explained.tokens == CARD_TEXT
