import pytest

from qpilot.core import robustness as rb
from qpilot.core.decisions import (
    AUTO_REASON_ELSEWHERE,
    CardSpec,
    DecisionError,
    OptionSpec,
    apply_decision,
    build_cards,
    effective_level,
    reject_request,
)
from tests.core.toy_space import ToySpace


def toy_specs():
    return [
        CardSpec(
            card_id="card_b",
            kind="group_cutoff",
            dimension="b",
            options=[
                OptionSpec(id="x", label="X", value="x"),
                OptionSpec(id="y", label="Y", value="y"),
            ],
            recommended="x",
            rationale_template="cutoff_v1",
        ),
        CardSpec(
            card_id="card_a",
            kind="reference_set",
            dimension="a",
            options=[OptionSpec(id=f"a{i}", label=f"A{i}", value=i) for i in range(3)],
            recommended="a0",
            rationale_template="refset_v1",
            facts=["f_n_genes"],
        ),
    ]


def test_effective_level():
    assert effective_level("decide_and_tell", {"flips": True}) == "suggest"
    assert effective_level("automatic", {"flips": True}) == "suggest"
    assert effective_level("decide_and_tell", {"flips": False}) == "decide_and_tell"
    assert effective_level("suggest", {"flips": True}) == "suggest"
    assert effective_level("teach", {"flips": True}) == "teach"


def test_build_cards_on_toy_space():
    space = ToySpace()
    summary = rb.summary(rb.run_grid(space), space)
    cards = build_cards(space, summary, toy_specs(), ["g1", "g2", "g3"], "decide_and_tell")
    assert [c.id for c in cards] == ["card_a", "card_b"]  # a has the larger shift (tie on flips)
    assert [c.rank for c in cards] == [1, 2]
    a = cards[0]
    assert a.impact["n_genes_flipped"] == 1 and a.impact["flips"] is True
    assert a.effective_autonomy == "suggest" and a.autonomy == "decide_and_tell"
    assert a.options[1].per_gene["g2"].conclusion == "none"
    assert a.options[0].per_gene["g2"].conclusion == "up"
    assert a.status == "open"


def test_card_that_flips_nothing_is_auto_decided():
    space = ToySpace()
    summary = rb.summary(rb.run_grid(space), space)
    for s in summary.values():
        s.impact["b"]["flips"] = False
    cards = build_cards(space, summary, toy_specs(), ["g1"])
    b = next(c for c in cards if c.id == "card_b")
    assert b.status == "auto_decided" and b.decided_by == "system"
    # at the primary settings nothing flips, but in the grid b does flip g3, so agents must ask
    assert b.decision == "x" and b.reason == AUTO_REASON_ELSEWHERE
    assert b.impact["flips_anywhere"] is True


def test_build_cards_rejects_bad_specs():
    space = ToySpace()
    summary = rb.summary(rb.run_grid(space), space)
    spec = toy_specs()[0]
    with pytest.raises(DecisionError):
        build_cards(space, summary, [spec.model_copy(update={"recommended": "zz"})], ["g1"])
    with pytest.raises(DecisionError):
        bad = spec.model_copy(update={"options": [OptionSpec(id="q", label="Q", value="q")]})
        build_cards(space, summary, [bad.model_copy(update={"recommended": "q"})], ["g1"])


def test_agent_on_flipping_card_is_pending_human(store, study):
    out = apply_decision(store, study, "card_refset", "hmbs_alone", "try", "agent")
    assert out.status == "pending_human"
    assert "human" in out.reason
    assert out.card.status == "pending_human"
    assert out.card.decision is None
    pending = store.pending(study)
    assert [(p.card_id, p.option, p.actor) for p in pending] == [
        ("card_refset", "hmbs_alone", "agent")
    ]


def test_system_actor_also_gated(store, study):
    out = apply_decision(store, study, "card_cutoff", "cut_10", "rule pack", "system")
    assert out.status == "pending_human"


def test_store_level_gate_cannot_be_bypassed(store, study):
    out = store.append_decision(study, "card_refset", "hmbs_alone", "direct", "agent", None)
    assert out.status == "pending_human"


def test_human_decides_and_clears_pending(store, study):
    apply_decision(store, study, "card_refset", "hmbs_alone", "try", "agent")
    out = apply_decision(store, study, "card_refset", "recommended", "keep all five", "human")
    assert out.status == "applied"
    assert out.card.status == "decided" and out.card.decided_by == "human"
    assert out.card.reason == "keep all five"
    assert store.pending(study) == []
    assert store.chain_head(study) == out.chain_head


def test_human_rejects_agent_request(store, study):
    apply_decision(store, study, "card_refset", "hmbs_alone", "try", "agent")
    out = reject_request(store, study, "card_refset", "HMBS alone is not stable here")
    assert out.status == "rejected"
    assert store.entries(study)[-1].option == "hmbs_alone"  # the refused option is logged
    assert out.card.status == "open" and out.card.decision is None
    assert store.pending(study) == []
    with pytest.raises(KeyError):
        reject_request(store, study, "card_refset", "nothing to reject")


def test_agent_may_apply_non_flipping_card(store, study):
    out = apply_decision(store, study, "card_undetermined", "cap", "cap is fine", "agent")
    assert out.status == "applied"
    assert out.card.decided_by == "agent" and out.card.decision == "cap"


def test_auto_decided_logged_as_system(store, study):
    entries = store.entries(study)
    assert [(e.card_id, e.actor, e.status) for e in entries] == [
        ("card_undetermined", "system", "auto")
    ]
    card = store.card(study, "card_undetermined")
    assert card.status == "auto_decided" and card.decided_by == "system"


def test_bad_option_and_reason(store, study):
    with pytest.raises(DecisionError):
        apply_decision(store, study, "card_refset", "nope", "x", "human")
    with pytest.raises(DecisionError):
        apply_decision(store, study, "card_refset", "recommended", "x" * 501, "human")
    with pytest.raises(DecisionError):
        apply_decision(store, study, "card_refset", "recommended", "   ", "human")
    with pytest.raises(KeyError):
        apply_decision(store, study, "card_nope", "recommended", "x", "human")


def test_stale_head_refused(store, study):
    head = store.chain_head(study)
    first = apply_decision(store, study, "card_refset", "recommended", "keep", "human", head)
    assert first.status == "applied"
    second = apply_decision(store, study, "card_refset", "hmbs_alone", "switch", "human", head)
    assert second.status == "stale"
    assert second.reason == "card changed since you read it"
    assert store.card(study, "card_refset").decision == "recommended"
    statuses = [e.status for e in store.entries(study)]
    assert statuses == ["auto", "applied"]  # a refused attempt never moves the chain head
    assert second.chain_head == first.chain_head == store.chain_head(study)
    assert [a["status"] for a in store.attempts(study)] == ["stale"]


def test_reject_logs_every_refused_option_and_checks_head(store, study):
    apply_decision(store, study, "card_cutoff", "cut_10", "agent wants 10%", "agent")
    apply_decision(store, study, "card_cutoff", "cut_20", "agent wants 20%", "agent")
    stale = reject_request(store, study, "card_cutoff", "no", expected_head="0" * 64)
    assert stale.status == "stale" and len(store.pending(study)) == 2
    out = reject_request(store, study, "card_cutoff", "keep 15 %", store.chain_head(study))
    assert out.status == "rejected" and store.pending(study) == []
    refused = [e.option for e in store.entries(study) if e.status == "rejected"]
    assert refused == ["cut_10", "cut_20"]


def test_reject_one_option_keeps_the_other(store, study):
    apply_decision(store, study, "card_cutoff", "cut_10", "a", "agent")
    apply_decision(store, study, "card_cutoff", "cut_20", "b", "agent")
    reject_request(store, study, "card_cutoff", "not 10", option="cut_10")
    assert [p.option for p in store.pending(study)] == ["cut_20"]
