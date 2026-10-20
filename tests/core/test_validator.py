import pytest

from qpilot.core.facts import FactRegistry, render_fact, slug
from qpilot.core.validator import names_from_result, render_tokens, validate
from qpilot.schemas import Fact

FACTS = {
    "f_fc_odc1_recommended": Fact(
        id="f_fc_odc1_recommended", value=3.589883, fmt="{:.2g}", unit="×"
    ),
    "f_holds_nm23a": Fact(id="f_holds_nm23a", value=0.645161, fmt="{:.0%}"),
    "f_n_genes": Fact(id="f_n_genes", value=58),
    "f_empty": Fact(id="f_empty", value=""),
}
NAMES = {"ODC1", "NM23A", "SDHA(1)", "UBC(2)", "MYCN(4)", "ALUsq(Eurogentec)"}

ADVERSARIAL = [
    "ODC1 is 3.6x up",
    "ODC1 is x2 higher",
    "holds in 95% of analyses",
    "holds in 95 % of analyses",
    "a 2-fold change",
    "fold change 3.59",
    "fold change of 3,590",
    "p = 0.001",
    "p < .05",
    "analysed on 2026-10-17",
    "on 17/10/2026",
    "in Q4",
    "MIQE 2.0 says so",
    "about −1.5 log2 units",
    "-1.5 log2 units",
    "+2 cycles",
    "1e-5",
    "twice as high (2×)",
    "{{f_unknown}} is up",
    "{{F_FC_ODC1_RECOMMENDED}} is up",
    "{{ f_fc_odc1_recommended }} is up",
    "{{f_empty}} genes",
    "{{f_fc_odc1_recommended}} and 31 genes flip",
    "{{f_n_genes}}0 genes",
    "ODC12 is up",
    "SDHA(12) is stable",
    "gene 7 of {{f_n_genes}}",
    "ODC1x3 shift",
    "³ levels",
    "rank #1",
]


@pytest.mark.parametrize("text", ADVERSARIAL)
def test_adversarial_rejected(text):
    result = validate(text, FACTS, NAMES)
    assert not result.ok, text


def test_thirty_adversarial_cases():
    assert len(ADVERSARIAL) == 30


@pytest.mark.parametrize(
    "text",
    [
        "ODC1 is {{f_fc_odc1_recommended}} higher in the high group.",
        "NM23A holds in {{f_holds_nm23a}} of the analyses; SDHA(1) and UBC(2) are references.",
        "Across {{f_n_genes}} genes, MYCN(4) defines the groups.",
        "No numbers at all.",
        "ALUsq(Eurogentec) is the most stable reference.",
    ],
)
def test_token_only_passes(text):
    assert validate(text, FACTS, NAMES).ok, validate(text, FACTS, NAMES).error()


def test_error_lists_reasons():
    result = validate("{{f_nope}} and 3.6x and {{f_empty}}", FACTS)
    assert result.unknown_ids == ["f_nope"]
    assert result.empty_ids == ["f_empty"]
    assert result.naked_numbers == ["3.6x"]
    assert "unknown fact ids" in result.error()


def test_gene_names_need_allowlist():
    assert not validate("ODC1 is up", FACTS).ok
    assert validate("ODC1 is up", FACTS, {"ODC1"}).ok


def test_render_tokens():
    text = "ODC1 {{f_fc_odc1_recommended}}; holds {{f_holds_nm23a}}; {{f_unknown}}"
    assert render_tokens(text, FACTS) == "ODC1 3.6×; holds 65%; {{f_unknown}}"


def test_registry_round_trip(fixture_facts):
    reg = FactRegistry(fixture_facts)
    assert len(reg) == len(fixture_facts)
    again = FactRegistry.from_json(reg.to_json())
    assert again.as_dict() == reg.as_dict()
    assert reg.render("f_fc_odc1_recommended") == "3.6×"
    assert reg.ids() == sorted(fixture_facts)


def test_registry_rejects_bad_ids():
    reg = FactRegistry()
    with pytest.raises(ValueError):
        reg.add(Fact(id="F_Bad", value=1))
    reg.add(Fact(id="f_a", value=1))
    reg.add(Fact(id="f_a", value=1))  # identical re-add is fine
    with pytest.raises(ValueError):
        reg.add(Fact(id="f_a", value=2))


def test_slug():
    assert slug("ALUsq(Eurogentec)") == "alusq_eurogentec"
    assert slug("SDHA(1)") == "sdha_1"
    assert slug("MYCN(4)") == "mycn_4"
    with pytest.raises(ValueError):
        slug("()")


def test_render_fact_unknown_format():
    assert render_fact(Fact(id="f_x", value="label", fmt="{:.2f}")) == "label"


def test_render_fact_never_writes_a_large_number_in_exponent_form():
    fold = Fact(id="f_x", value=123.4, fmt="{:.2g}", unit="×")
    assert render_fact(fold) == "120×"  # not 1.2e+02×
    assert render_fact(fold.model_copy(update={"value": 1.8e14})) == "180000000000000×"
    assert render_fact(fold.model_copy(update={"value": 99.6})) == "100×"
    assert render_fact(fold.model_copy(update={"value": 3.589883})) == "3.6×"
    assert render_fact(Fact(id="f_p", value=3.2e-07, fmt="{:.2g}")) == "3.2e-07"


def test_fixture_card_facts_render(fixture_cards, fixture_facts):
    for card in fixture_cards:
        prose = " ".join("{{" + fid + "}}" for fid in card.facts)
        assert validate(prose, fixture_facts).ok, card.id


def test_names_from_result(fixture_result):
    names = names_from_result(fixture_result)
    assert {"ODC1", "SDHA(1)", "UBC(2)", "MYCN_high"} <= names


def test_names_inside_parentheses_and_lists():
    text = "Top two (ALUsq(Eurogentec), HPRT1) and SDHA(1), UBC(2)."
    assert validate(text, FACTS, NAMES | {"HPRT1"}).ok
    assert not validate("SDHA(12) and UBC(2)", FACTS, NAMES).ok


def test_method_constants_allowed_but_data_still_rejected(fixture_result):
    names = names_from_result(fixture_result)
    ok = (
        "NM23A is up (95% confidence interval {{f_ci_lo_nm23a_recommended}}); "
        "the rule is p < 0.05 and a change of at least 2-fold."
    )
    assert validate(ok, fixture_result.facts, names).ok
    assert validate("the two-fold line and the 95 % CI", fixture_result.facts, names).ok
    for bad in ["NM23A is 2.2x up", "holds in 65% of analyses", "97% of analyses", "3-fold change"]:
        assert not validate(bad, fixture_result.facts, names).ok, bad


@pytest.mark.parametrize(
    "bad",
    [
        "ODC1 rises 2x under the recommended set.",
        "NM23A rises 2× when SDHA(1) is the only control gene.",
        "ODC1 holds in 95% of the reasonable analyses.",
        "ODC1 has p = 0.05.",
        "ODC1 is about seven-fold higher.",
        "It holds in ninety-five percent of analyses.",
        "Roughly half of the samples are high.",
        "ODC1 rises three fold.",
    ],
)
def test_method_numbers_outside_their_method_wording_are_data(fixture_result, bad):
    assert not validate(bad, fixture_result.facts, names_from_result(fixture_result)).ok
