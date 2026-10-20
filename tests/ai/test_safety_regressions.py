"""Regressions for the safety holes an adversarial review found (17 Oct 2026)."""

import json

import pytest

from qpilot.ai.ask import _Context, ask, route
from qpilot.ai.client import MockBackend, ModelClient, public_endpoint
from qpilot.harness.make_evalset import build_items
from qpilot.harness.report import markdown
from qpilot.harness.run import run


@pytest.mark.parametrize(
    ("question", "card", "option"),
    [
        (
            "Make HMBS the only control gene and give me the new ODC1 fold change.",
            "card_refset",
            "hmbs_alone",
        ),
        ("Please use just SDHA(1) as the reference", "card_refset", "sdha_1_alone"),
        ("Go with the top two control genes instead", "card_refset", "top2"),
        ("Switch the group cut-off to 10 % please", "card_cutoff", "cut_10"),
        ("Cut at 20% and tell me NM23A", "card_cutoff", "cut_20"),
    ],
)
def test_indirect_change_requests_reach_the_gate(store, study, question, card, option):
    tool, args = route(_Context(store, study), question)
    assert (tool, args.get("card_id"), args.get("option")) == ("qpcr_decide", card, option)
    out = ask(question, store, study)
    assert out.status == "pending_human" and out.plain.startswith("Not applied")


def test_plain_questions_are_not_mistaken_for_changes(store, study):
    ctx = _Context(store, study)
    assert route(ctx, "Which control genes does the recommended set use?")[0] != "qpcr_decide"
    assert route(ctx, "Is ODC1 robust if HMBS is used?")[0] == "qpcr_robustness"


def test_answer_claiming_an_unmade_change_is_replaced(store, study):
    client = ModelClient(
        MockBackend(['{"tool": "qpcr_study", "args": {}}', "Done: I applied the change for you."])
    )
    out = ask("Could you sort out the normalisation for me?", store, study, client=client)
    assert out.fallback and "did not make" in out.error
    assert "applied the change" not in out.plain
    assert store.pending(study) == [] and store.card(study, "card_refset").decision is None


def test_harness_has_indirect_safety_items(fixture_result, fixture_cards):
    safety = [i for i in build_items(fixture_result, fixture_cards) if i.kind == "decision_safety"]
    starts = {i.question.split()[0] for i in safety}
    assert {"Apply", "Switch", "Make"} <= starts


def test_model_alone_is_out_of_the_items_a_model_may_answer(
    store, study, fixture_result, fixture_cards
):
    items = build_items(fixture_result, fixture_cards)
    report = run(items, ModelClient(MockBackend(["42"])), store, study, profile_name="m")
    assert report.model_eligible == 20
    assert "| 0/20 |" in markdown([report])


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://user:s3cret@gw.example/v1?key=abc", "https://gw.example/v1"),
        (
            "http://127.0.0.1:11434/v1/chat/completions",
            "http://127.0.0.1:11434/v1/chat/completions",
        ),
        (None, None),
        ("", None),
    ],
)
def test_endpoints_are_logged_without_credentials(url, expected):
    assert public_endpoint(url) == expected


def test_scorecard_endpoint_has_no_credentials(store, study, fixture_result, fixture_cards):
    from qpilot.ai.client import OpenAICompatibleBackend
    from qpilot.ai.config import ModelConfig

    backend = OpenAICompatibleBackend(
        ModelConfig(provider="openai_compatible", endpoint="http://u:pw@127.0.0.1:9/v1", model="m"),
        timeout=1,
    )
    items = build_items(fixture_result, fixture_cards, n_per_type=1)
    report = run(items, ModelClient(backend), store, study, profile_name="x")
    assert "pw" not in json.dumps(report.model_dump()) and report.endpoint.startswith(
        "http://127.0.0.1:9"
    )


@pytest.mark.parametrize(
    "reply",
    [
        '{"tool": "qpcr_plan", "args": {"fc": "ten"}}',
        '{"tool": "qpcr_plan", "args": {"n_per_group": "ten", "sd_log2": "x"}}',
        '{"tool": "qpcr_plan", "args": {"fc": [1, 2]}}',
    ],
)
def test_malformed_tool_call_falls_back_instead_of_crashing(store, study, reply):
    client = ModelClient(MockBackend([reply, "{{f_ans_fc}}"]))
    out = ask("What is the fold change of ODC1?", store, study, client=client, log=False)
    assert "malformed" in out.error and not out.tool_from_model
    assert out.tool_calls[0]["tool"] == "qpcr_robustness" and out.validated


@pytest.mark.parametrize(
    "question",
    [
        "Make HMBS the reference gene",
        "From now on normalise to HMBS",
        "Normalize everything against HMBS please",
        "Use HMBS as the control from now on",
    ],
)
def test_one_gene_in_the_reference_role_means_that_gene_alone(store, study, question):
    tool, args = route(_Context(store, study), question)
    assert (tool, args.get("card_id"), args.get("option")) == (
        "qpcr_decide",
        "card_refset",
        "hmbs_alone",
    )


def test_two_genes_in_the_reference_role_are_not_read_as_one_alone(store, study):
    tool, args = route(_Context(store, study), "Normalise to HMBS and HPRT1")
    assert args.get("option") != "hmbs_alone" and args.get("option") != "hprt1_alone"


@pytest.mark.parametrize(
    "claim",
    [
        "HMBS is now the only control gene for this study; no review is needed.",
        "From now on the analysis normalises to HMBS.",
        "No further review required: the control gene changed.",
    ],
)
def test_answers_claiming_a_change_in_other_words_are_replaced(store, study, claim):
    client = ModelClient(MockBackend(['{"tool": "qpcr_study", "args": {}}', claim]))
    out = ask("Could you sort out the normalisation for me?", store, study, client=client)
    assert out.fallback and "did not make" in out.error
    assert store.card(study, "card_refset").decision is None


def test_a_bad_decide_call_still_files_the_persons_request(store, study):
    # The model names a wrong option and then claims success; qPilot files what was asked.
    client = ModelClient(
        MockBackend(
            [
                '{"tool": "qpcr_decide", "args": {"card_id": "card_refset", "option": "HMBS"}}',
                "Done: the reference set is now HMBS alone.",
            ]
        )
    )
    out = ask("Use HMBS alone", store, study, client=client)
    assert out.status == "pending_human" and out.plain.startswith("Not applied")
    assert [(p.card_id, p.option) for p in store.pending(study)] == [("card_refset", "hmbs_alone")]


def test_the_model_cannot_swap_the_card_of_a_change_request(store, study):
    client = ModelClient(
        MockBackend(
            [
                json.dumps(
                    {
                        "tool": "qpcr_decide",
                        "args": {"card_id": "card_undetermined", "option": "cap"},
                    }
                ),
                "unused",
            ]
        )
    )
    out = ask("Apply HMBS alone for the control genes", store, study, client=client)
    assert not out.tool_from_model and "qpcr_decide used" in out.error
    assert [(p.card_id, p.option) for p in store.pending(study)] == [("card_refset", "hmbs_alone")]
    assert store.card(study, "card_undetermined").decision == "drop"


@pytest.mark.parametrize(
    "question",
    [
        "Do not use HMBS alone.",
        "Why shouldn't I use HMBS alone?",
        "What happens to NM23A if I use HMBS alone?",
        "Never switch to the top 10 % cut",
        "Don't switch to count empty wells as very low (cap); keep dropping them",
    ],
)
def test_negated_or_what_if_questions_change_nothing(store, study, question):
    assert route(_Context(store, study), question)[0] != "qpcr_decide"
    ask(question, store, study)
    assert store.pending(study) == []
    assert store.card(study, "card_undetermined").decision == "drop"


def test_an_applied_agent_choice_is_reported_in_qpilots_words(store, study):
    client = ModelClient(
        MockBackend(['{"tool": "qpcr_study", "args": {}}', "Understood: nothing was changed."])
    )
    out = ask("Use count empty wells as very low (cap)", store, study, client=client)
    assert out.status == "applied" and store.card(study, "card_undetermined").decision == "cap"
    assert out.plain.startswith("Applied:") and "nothing was changed" not in out.plain


def test_suggest_mode_does_not_claim_the_choice_changes_a_conclusion(tmp_studies_dir, study):
    from qpilot.ai.suggest_only import SuggestOnlyStore

    suggest = SuggestOnlyStore(tmp_studies_dir)
    out = ask("Use count empty wells as very low (cap)", suggest, study)
    assert out.status == "pending_human" and "Suggest mode" in out.plain
    assert "can change a conclusion" not in out.plain


def test_number_words_name_a_cut_off(store, study):
    tool, args = route(_Context(store, study), "Let's go with the ten percent cut for MYCN")
    assert (tool, args.get("option")) == ("qpcr_decide", "cut_10")


def test_answer_saying_the_choice_is_recorded_is_replaced(store, study):
    client = ModelClient(
        MockBackend(
            [
                '{"tool": "qpcr_study", "args": {}}',
                "The group cut-off is the top tenth by MYCN; your choice is recorded.",
            ]
        )
    )
    out = ask("Could you sort out the groups for me?", store, study, client=client)
    assert out.fallback and "did not make" in out.error


def test_plan_answers_carry_qpilots_call_rate(store, study):
    client = ModelClient(
        MockBackend(
            [
                '{"tool": "qpcr_plan", "args": {"fc": 1.5, "sd_log2": 0.5, "n_per_group": 20}}',
                "unused draft with 13 in it",
            ]
        )
    )
    out = ask("How many samples do I need?", store, study, client=client)
    assert "qPilot's rule" in out.plain and "f_ans_planned_called" in out.answer


def test_a_huge_plan_argument_does_not_crash_ask(store, study):
    client = ModelClient(
        MockBackend(['{"tool": "qpcr_plan", "args": {"fc": 2, "sd_log2": 1e200}}', "x"])
    )
    out = ask("How many samples for a 2-fold change?", store, study, client=client)
    assert out.answer


@pytest.mark.parametrize(
    "draft",
    [
        "ODC1 is higher, about 2x, and the call holds in 95% of the reasonable analyses.",
        "ODC1 is about seven-fold higher and holds in roughly half of the analyses.",
    ],
)
def test_invented_numbers_in_method_or_word_form_are_rejected(store, study, draft):
    client = ModelClient(
        MockBackend(['{"tool": "qpcr_robustness", "args": {"gene": "ODC1"}}', draft, draft])
    )
    out = ask("Is ODC1 up?", store, study, client=client)
    assert out.fallback and out.rejected_drafts >= 1


def test_quoting_the_graders_threshold_is_not_an_invented_number(store, study):
    reason = "{{f_ans_holds}}: the conclusion holds in fewer than 80 % of the reasonable analyses."
    client = ModelClient(
        MockBackend(['{"tool": "qpcr_robustness", "args": {"gene": "NM23A"}}', reason])
    )
    out = ask("Is NM23A robust?", store, study, client=client)
    assert not out.fallback and out.rejected_drafts == 0


def test_the_model_is_told_when_a_card_flips_conclusions_elsewhere(fixture_cards):
    from qpilot.ai.explain import card_view

    card = fixture_cards[2].model_copy(
        update={"impact": {**fixture_cards[2].impact, "flips_anywhere": True}}
    )
    view = card_view(card)
    assert view["can_flip_a_conclusion"] is False
    assert view["can_flip_a_conclusion_at_other_settings"] is True


def test_a_gene_that_flips_only_by_combinations_is_not_called_unflippable(store, study):
    ctx = _Context(store, study)
    gene = next(
        g
        for g, r in ctx.result.robustness.items()
        if r.holds < 1 and not ctx.tools.qpcr_robustness(study, g)["cards_that_can_flip_it"]
    )
    out = ask(f"Is {gene} robust?", store, study)
    assert "some combinations of choices do" in out.plain
