import json

import pytest

from qpilot.ai import payload_log
from qpilot.ai.ask import NOT_IN_STUDY, _Context, ask, route
from qpilot.ai.client import (
    MockBackend,
    ModelClient,
    ModelUnavailable,
    NoneBackend,
    OpenAICompatibleBackend,
    make_backend,
)
from qpilot.ai.config import ModelConfig
from qpilot.ai.explain import explain_card, template_explanation
from qpilot.ai.profile import autonomy_policy, build_fewshots, load_profile
from qpilot.core.validator import validate


def mock(*replies):
    return ModelClient(MockBackend(list(replies)))


# ---- config and client ------------------------------------------------------------------


def test_default_provider_is_none():
    cfg = ModelConfig.from_env()
    assert cfg.provider == "none"
    client = ModelClient.from_env()
    assert isinstance(client.backend, NoneBackend) and not client.available
    with pytest.raises(ModelUnavailable):
        client.complete("s", [])
    assert client.ping() is False


def test_config_never_shows_key(monkeypatch):
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "openai_compatible")
    monkeypatch.setenv("QPILOT_API_KEY", "sk-secret-value")
    cfg = ModelConfig.from_env()
    assert "sk-secret-value" not in repr(cfg) and "sk-secret-value" not in str(cfg.describe())
    assert cfg.describe()["api_key"] == "set"


def test_bad_provider(monkeypatch):
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "openai")
    with pytest.raises(ValueError):
        ModelConfig.from_env()


def test_backends_need_their_settings():
    with pytest.raises(ModelUnavailable):
        make_backend(ModelConfig(provider="openai_compatible", model="m"))
    with pytest.raises(ModelUnavailable):
        make_backend(ModelConfig(provider="anthropic", model="m"))
    # a misconfigured client degrades to templates instead of crashing
    assert not ModelClient(config=ModelConfig(provider="anthropic")).available


def test_openai_url_building():
    b = OpenAICompatibleBackend(
        ModelConfig(provider="openai_compatible", endpoint="http://h:1/v1/", model="m")
    )
    assert b.url == "http://h:1/v1/chat/completions"
    b = OpenAICompatibleBackend(
        ModelConfig(provider="openai_compatible", endpoint="http://h:1", model="m")
    )
    assert b.url == "http://h:1/v1/chat/completions"


def test_openai_backend_unreachable_is_unavailable():
    b = OpenAICompatibleBackend(
        ModelConfig(provider="openai_compatible", endpoint="http://127.0.0.1:9", model="m"),
        timeout=1,
    )
    with pytest.raises(ModelUnavailable):
        b.complete("s", [{"role": "user", "content": "x"}], 5, 0)


def test_payload_is_recorded():
    client = mock("hi")
    client.complete("system text", [{"role": "user", "content": "hello"}])
    seen = payload_log.last_payload()
    assert seen["system"] == "system text" and seen["provider"] == "mock"
    assert len(client.last_meta["payload_sha256"]) == 64


# ---- explain ------------------------------------------------------------------------------


def test_explain_valid_token_answer(fixture_cards, fixture_facts):
    card = fixture_cards[0]
    client = mock("{{f_n_flipped_refset}} genes change with this choice; keep HMBS? No, all five.")
    out = explain_card(card, fixture_facts, client=client)
    assert out.validated and not out.fallback
    assert "31 genes" in out.plain


def test_explain_naked_number_retries_then_falls_back(fixture_cards, fixture_facts):
    card = fixture_cards[0]
    backend = MockBackend(["31 genes flip.", "Still 31 genes."])
    out = explain_card(card, fixture_facts, client=ModelClient(backend))
    assert out.fallback and "numbers not written" in out.error
    assert len(backend.calls) == 2  # one retry
    assert "Rejected" in backend.calls[1]["messages"][-1]["content"]
    assert validate(out.tokens, fixture_facts, {"HMBS"}).ok or out.validated


def test_explain_retry_can_succeed(fixture_cards, fixture_facts):
    client = mock("31 genes flip.", "{{f_n_flipped_refset}} genes flip.")
    out = explain_card(fixture_cards[0], fixture_facts, client=client)
    assert out.validated and not out.fallback


def test_explain_without_model_uses_template(fixture_cards, fixture_facts):
    out = explain_card(fixture_cards[0], fixture_facts)
    assert out.fallback and out.provider == "none" and out.validated
    assert out.tokens == template_explanation(fixture_cards[0], fixture_facts)
    assert "31 genes" in out.plain


def test_model_never_sees_raw_numbers(fixture_cards, fixture_facts):
    backend = MockBackend(["{{f_n_flipped_refset}} genes."])
    explain_card(fixture_cards[0], fixture_facts, client=ModelClient(backend))
    payload = json.loads(backend.calls[0]["messages"][0]["content"])
    assert "per_gene" not in json.dumps(payload["card"])
    assert set(payload["facts"]) <= set(fixture_cards[0].facts)


# ---- ask ----------------------------------------------------------------------------------


def test_ask_template_lookup(store, study):
    out = ask("What is the fold change of ODC1?", store, study)
    assert out.fallback and out.validated and out.provider == "none"
    assert out.tool_calls[0]["tool"] == "qpcr_robustness"
    assert "3.6×" in out.plain and "100%" in out.plain and "Moderate" in out.plain


def test_ask_template_refusal(store, study):
    out = ask("What is the p-value for GAPDH?", store, study)
    assert NOT_IN_STUDY in out.plain and out.validated
    assert out.tool_calls[0]["tool"] == "none"


def test_ask_template_decide_is_pending_human(store, study):
    out = ask(
        "Apply HMBS alone as the control gene and tell me the new ODC1 fold change", store, study
    )
    assert out.status == "pending_human"
    assert "person must decide" in out.plain
    assert store.card(study, "card_refset").decision is None
    assert [p.option for p in store.pending(study)] == ["hmbs_alone"]


def test_ask_with_model_tool_call_and_tokens(store, study):
    client = mock(
        '{"tool": "qpcr_robustness", "args": {"gene": "NM23A"}}',
        "NM23A is up at {{f_ans_fc}} but holds in only {{f_ans_holds}} of analyses.",
    )
    out = ask("Is NM23A robust?", store, study, client=client)
    assert out.validated and not out.fallback and out.rejected_drafts == 0
    assert "2.2×" in out.plain and "65%" in out.plain
    calls = store.ai_calls(study)
    assert len(calls) == 1 and calls[0]["validated"] and "payload" not in calls[0]


def test_ask_model_naked_number_falls_back(store, study):
    client = mock(
        '{"tool": "qpcr_robustness", "args": {"gene": "ODC1"}}', "ODC1 is 3.6x up.", "3.6x"
    )
    out = ask("ODC1?", store, study, client=client)
    assert out.fallback and out.rejected_drafts == 2
    assert out.validated  # the template that replaced it is valid
    assert store.ai_calls(study)[0]["fallback"] is True


def test_ask_model_decide_reports_pending(store, study):
    client = mock(
        json.dumps(
            {
                "tool": "qpcr_decide",
                "args": {"card_id": "card_refset", "option": "hmbs_alone", "reason": "asked"},
            }
        ),
        "Done, switched to HMBS.",
    )
    out = ask("Switch to HMBS alone", store, study, client=client)
    assert out.status == "pending_human"
    assert out.fallback and "person must decide" in out.plain  # misleading answer replaced
    assert store.card(study, "card_refset").decision is None


def test_ask_bad_tool_json_uses_routing(store, study):
    client = mock("not json at all", "{{f_ans_fc}}")
    out = ask("What is the fold change of BIRC5?", store, study, client=client)
    assert out.tool_calls[0]["args"] == {"gene": "BIRC5"}
    assert "did not parse" in out.error


def test_ask_payload_has_no_sample_names(store, study, fixture_result):
    client = mock('{"tool": "qpcr_study", "args": {}}', "There are {{f_ans_n_plates}} plates.")
    out = ask("How many plates?", store, study, client=client)
    assert "64 plates" in out.plain
    seen = json.dumps(payload_log.last_payload())
    assert "input_sha256" not in seen and fixture_result.input_sha256 not in seen


def test_ask_logs_raw_payload_only_when_asked(store, study, monkeypatch):
    monkeypatch.setenv("QPILOT_LOG_PAYLOAD", "1")
    ask(
        "ODC1?",
        store,
        study,
        client=mock('{"tool": "qpcr_robustness", "args": {"gene": "ODC1"}}', "{{f_ans_fc}}"),
    )
    assert "payload" in store.ai_calls(study)[0]


def test_route_examples(store, study):
    ctx = _Context(store, study)
    assert route(ctx, "is odc1 up?") == ("qpcr_robustness", {"gene": "ODC1"})
    assert route(ctx, "How many plates are there?") == ("qpcr_study", {})
    assert route(ctx, "Tell me about TP53")[0] == "none"
    assert route(ctx, "What does MYCN high mean?")[0] == "qpcr_study"
    assert route(ctx, "use SDHA(1) alone please")[1]["option"] == "sdha_1_alone"


# ---- profile ------------------------------------------------------------------------------


def test_profile_and_fewshots(tmp_path, store, study):
    path = tmp_path / "p.yaml"
    path.write_text(
        "name: lab\nconventions: [report CI]\nautonomy_policy: ignored\nmax_fewshots: 2\n"
    )
    prof = load_profile(path)
    assert prof.name == "lab" and prof.max_fewshots == 2
    store.append_decision(study, "card_refset", "top2", "the two most stable", "human", None)
    store.append_decision(study, "card_undetermined", "cap", "agent idea", "agent", None)
    shots = build_fewshots(store.entries(study), store.cards(study))
    assert shots == [
        {
            "card": "reference_set",
            "choice": "Top two by stability (ALUsq(Eurogentec), HPRT1)",
            "reason": "the two most stable",
        }
    ]
    assert len(autonomy_policy()) == 3
    (tmp_path / "bad.yaml").write_text("- a list\n")
    with pytest.raises(ValueError):
        load_profile(tmp_path / "bad.yaml")


def test_explain_knows_reference_names_from_evidence(fixture_cards, fixture_facts):
    from qpilot.ai.explain import card_names

    assert {"HPRT1", "SDHA(1)", "UBC(2)"} <= card_names(fixture_cards[0])
    client = mock("HPRT1 and SDHA(1), UBC(2)) are candidates; {{f_n_flipped_refset}} genes flip.")
    assert explain_card(fixture_cards[0], fixture_facts, client=client).validated


def test_fact_table_gives_token_to_write(fixture_cards, fixture_facts):
    backend = MockBackend(["{{f_n_flipped_refset}} genes."])
    explain_card(fixture_cards[0], fixture_facts, client=ModelClient(backend))
    table = json.loads(backend.calls[0]["messages"][0]["content"])["facts"]
    entry = table["f_n_flipped_refset"]
    assert entry["write_exactly"] == "{{f_n_flipped_refset}}"
    assert entry["value_for_reading_only"] == "31"


def test_change_request_cannot_dodge_the_gate_by_tool_choice(store, study):
    # The model answers a change request with a lookup; qPilot still routes it to the gate.
    client = mock(
        '{"tool": "qpcr_robustness", "args": {"gene": "BIRC5"}}',
        "Not applied; a person must decide this.",
    )
    q = "Apply SDHA(1) alone for the control genes and tell me the new BIRC5 fold change."
    out = ask(q, store, study, client=client)
    assert out.tool_calls[0]["tool"] == "qpcr_decide"
    assert out.status == "pending_human"
    assert "qpcr_decide used" in out.error
    assert store.card(study, "card_refset").decision is None
