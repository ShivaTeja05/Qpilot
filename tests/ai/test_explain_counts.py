"""A model's explanation must cite the counts its card is about, or the template is used."""

import json

from qpilot.ai.client import MockBackend, ModelClient
from qpilot.ai.explain import explain_card, required_facts, template_explanation
from qpilot.schemas import CardOption, DecisionCard, Fact

RULES = {
    "linregpcr": "LinRegPCR's own call",
    "cq_le_35": "a Cq cut-off at thirty-five",
    "cq_le_38": "a Cq cut-off at thirty-eight",
}
FLIPS = {"linregpcr": 0, "cq_le_35": 10, "cq_le_38": 3}


def _amp_card() -> tuple[DecisionCard, dict[str, Fact]]:
    """An amplification-call card and its facts, shaped like ``qpcr.study`` builds them."""
    facts = {
        "f_n_flipped_amp_call": Fact(id="f_n_flipped_amp_call", value=10),
        "f_n_genes": Fact(id="f_n_genes", value=60),
        "f_amp_primary": Fact(id="f_amp_primary", value=RULES["linregpcr"]),
    }
    for rule, label in RULES.items():
        facts[f"f_amp_label_{rule}"] = Fact(id=f"f_amp_label_{rule}", value=label)
        facts[f"f_n_flipped_amp_{rule}"] = Fact(id=f"f_n_flipped_amp_{rule}", value=FLIPS[rule])
        facts[f"f_n_undetermined_amp_{rule}"] = Fact(
            id=f"f_n_undetermined_amp_{rule}", value=5 * FLIPS[rule]
        )
    card = DecisionCard(
        id="card_amp_call",
        kind="amp_call",
        rank=4,
        impact={"flips": True},
        evidence={},
        options=[CardOption(id=rule, label=label, per_gene={}) for rule, label in RULES.items()],
        recommended="linregpcr",
        rationale_template="ampcall_v1",
        facts=list(facts),
    )
    return card, facts


LABELS_ONLY = (
    "This card chooses between {{f_amp_label_linregpcr}}, {{f_amp_label_cq_le_35}} and "
    "{{f_amp_label_cq_le_38}}; {{f_amp_primary}} is recommended and a person decides."
)
COMPLETE = (
    "With {{f_amp_label_cq_le_35}}, {{f_n_flipped_amp_cq_le_35}} genes change their "
    "conclusion, and with {{f_amp_label_cq_le_38}}, {{f_n_flipped_amp_cq_le_38}}; "
    "{{f_amp_primary}} is recommended and a person decides."
)


def test_the_counts_an_amp_call_explanation_must_cite():
    card, facts = _amp_card()
    # the rule in use is the analysis itself: its own count is zero by construction
    assert required_facts(card, facts) == ["f_n_flipped_amp_cq_le_35", "f_n_flipped_amp_cq_le_38"]


def test_a_valid_explanation_without_the_flip_counts_falls_back_to_the_template():
    card, facts = _amp_card()
    backend = MockBackend([LABELS_ONLY])
    out = explain_card(card, facts, client=ModelClient(backend))
    assert out.fallback and out.validated  # validated: the template itself passes
    assert out.tokens == template_explanation(card, facts)
    assert "{{f_n_flipped_amp_cq_le_35}}" in out.tokens
    assert len(backend.calls) == 2  # one retry, told what is missing
    retry = backend.calls[1]["messages"][-1]["content"]
    assert "{{f_n_flipped_amp_cq_le_35}}" in retry and "{{f_n_flipped_amp_cq_le_38}}" in retry
    assert "does not cite" in out.error
    first = json.loads(backend.calls[0]["messages"][0]["content"])
    assert first["must_cite"] == ["{{f_n_flipped_amp_cq_le_35}}", "{{f_n_flipped_amp_cq_le_38}}"]


def test_an_explanation_citing_every_flip_count_is_used():
    card, facts = _amp_card()
    out = explain_card(card, facts, client=ModelClient(MockBackend([COMPLETE])))
    assert out.validated and not out.fallback and out.tokens == COMPLETE
    # the retry can supply what the first reply left out
    backend = MockBackend([LABELS_ONLY, COMPLETE])
    out = explain_card(card, facts, client=ModelClient(backend))
    assert out.validated and not out.fallback and len(backend.calls) == 2


def test_other_cards_need_their_own_flip_count(fixture_cards, fixture_facts):
    card = fixture_cards[0]
    assert required_facts(card, fixture_facts) == ["f_n_flipped_refset"]
    backend = MockBackend(["Which control genes to use is a judgement call; a person decides."])
    out = explain_card(card, fixture_facts, client=ModelClient(backend))
    assert out.fallback and out.tokens == template_explanation(card, fixture_facts)
