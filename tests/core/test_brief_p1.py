"""Brief P1: escalation anywhere in the grid (E), Suggest for MCP agents (F), consistency (G)."""

import pytest

from qpilot.core import robustness as rb
from qpilot.core.decisions import CardSpec, OptionSpec, apply_decision, build_cards, needs_human
from qpilot.mcp_server import QpilotTools
from tests.core.toy_space import ToySpace


class OffPrimaryToySpace(ToySpace):
    """g4 flips on b only when a == 2, i.e. never with a at its primary value."""

    def __init__(self):
        super().__init__()
        self.items = [*self.items, "g4"]

    def evaluate(self, cell):
        out = super().evaluate(cell)
        flipped = cell["a"] == 2 and cell["b"] == "y"
        out["g4"] = out["g1"].model_copy(
            update={
                "target": "g4",
                "log2fc": 0.2 if flipped else 2.0,
                "fc": 1.15 if flipped else 4.0,
            }
        )
        out["g3"] = out["g1"].model_copy(update={"target": "g3"})  # b no longer flips g3
        return out


def _cards(space):
    grid = rb.run_grid(space)
    summary = rb.summary(grid, space)
    spec = CardSpec(
        card_id="card_b",
        kind="undetermined",
        dimension="b",
        options=[
            OptionSpec(id="x", label="X", value="x"),
            OptionSpec(id="y", label="Y", value="y"),
        ],
        recommended="x",
        rationale_template="t",
    )
    return grid, build_cards(space, summary, [spec], ["g1"])


def test_flip_away_from_the_primary_cell_is_found():
    space = OffPrimaryToySpace()
    grid, cards = _cards(space)
    assert rb.flipped_anywhere(grid, "b") == ["g4"]
    card = cards[0]
    assert card.impact["flips"] is False and card.status == "auto_decided"  # counter unchanged
    assert card.impact["flips_anywhere"] is True and card.impact["n_genes_flipped_anywhere"] == 1
    assert needs_human(card)


def test_agent_needs_a_person_for_a_choice_that_flips_elsewhere(store, fixture_result):
    space = OffPrimaryToySpace()
    _, cards = _cards(space)
    store.put(fixture_result, cards)
    out = apply_decision(store, fixture_result.study_id, "card_b", "y", "agent idea", "agent")
    assert out.status == "pending_human"


def test_mcp_agents_only_ask_until_the_scientist_allows_more(store, study):
    tools = QpilotTools(store)
    assert store.autonomy(study) == "suggest"
    out = tools.qpcr_decide(study, "card_undetermined", "cap", "agent idea")
    assert (
        out["status"] == "pending_human"
        and store.card(study, "card_undetermined").decision == "drop"
    )
    store.set_autonomy(study, "decide_and_tell")
    assert store.autonomy(study) == "decide_and_tell"
    out = tools.qpcr_decide(study, "card_undetermined", "cap", "agent idea")
    assert out["status"] == "applied"
    # still never for a choice that can change a conclusion
    assert tools.qpcr_decide(study, "card_refset", "hmbs_alone", "x")["status"] == "pending_human"
    with pytest.raises(ValueError):
        store.set_autonomy(study, "automatic")


def test_in_app_tools_follow_the_app_not_the_mcp_policy(store, study):
    tools = QpilotTools(store, agent_policy=False)
    assert tools.qpcr_decide(study, "card_undetermined", "cap", "x")["status"] == "applied"


def test_snapshot_reads_head_cards_and_pending_together(store, study):
    apply_decision(store, study, "card_refset", "hmbs_alone", "agent", "agent")
    head, cards, pending = store.snapshot(study)
    assert head == store.chain_head(study)
    assert [c.id for c in cards] == [c.id for c in store.cards(study)]
    assert [p.option for p in pending] == ["hmbs_alone"]


def test_an_applied_decision_clears_waiting_requests_on_that_card(store, study):
    tools = QpilotTools(store)
    tools.qpcr_decide(study, "card_undetermined", "cap", "asked in suggest mode")
    assert [p.card_id for p in store.pending(study)] == ["card_undetermined"]
    store.set_autonomy(study, "decide_and_tell")
    assert (
        tools.qpcr_decide(study, "card_undetermined", "cap", "now allowed")["status"] == "applied"
    )
    assert store.pending(study) == []


def test_record_from_a_study_with_attempts_and_autonomy_verifies(store, study, tmp_path):
    from qpilot.core.record import verify, write_record

    store.set_autonomy(study, "decide_and_tell")
    apply_decision(store, study, "card_refset", "top2", "x", "human", "0" * 64)  # stale
    info = write_record(store, study, tmp_path / "rec")
    names = {p.name for p in (tmp_path / "rec").iterdir()}
    assert {"attempts.jsonl", "autonomy.json"} <= names
    assert verify(info.record_dir).ok


@pytest.mark.demo_data
def test_demo_empty_wells_card_needs_a_person_at_the_twenty_percent_cut(store, demo_rdml_path):
    sid = store.ensure_study(demo_rdml_path)
    card = store.card(sid, "card_undetermined")
    assert card.status == "auto_decided" and card.impact["flips"] is False
    assert card.impact["flips_anywhere"] is True  # e.g. PLAGL1 and PTPRF at the 20 % cut
    apply_decision(store, sid, "card_cutoff", "cut_20", "pre-registered", "human")
    store.set_autonomy(sid, "decide_and_tell")
    out = QpilotTools(store).qpcr_decide(sid, "card_undetermined", "cap", "agent idea")
    assert out["status"] == "pending_human"


def test_agent_requests_elsewhere_never_block_a_person(store, study):
    head = store.chain_head(study)
    tools = QpilotTools(store)
    for _ in range(3):
        assert (
            tools.qpcr_decide(study, "card_cutoff", "cut_20", "again")["status"] == "pending_human"
        )
    out = apply_decision(store, study, "card_refset", "recommended", "five", "human", head)
    assert out.status == "applied"


def test_a_persons_decision_elsewhere_still_marks_the_page_out_of_date(store, study):
    head = store.chain_head(study)
    apply_decision(store, study, "card_cutoff", "cut_20", "other tab", "human", head)
    out = apply_decision(store, study, "card_refset", "recommended", "five", "human", head)
    assert out.status == "stale" and out.chain_head == store.chain_head(study)


def test_a_new_request_on_the_card_makes_turning_requests_down_stale(store, study):
    from qpilot.core.decisions import reject_request

    tools = QpilotTools(store)
    tools.qpcr_decide(study, "card_refset", "hmbs_alone", "agent A")
    seen = store.chain_head(study)
    tools.qpcr_decide(study, "card_refset", "top2", "agent B")  # not seen by the person
    assert reject_request(store, study, "card_refset", "no", seen).status == "stale"


def test_a_workspace_from_an_older_qpilot_is_reanalysed_keeping_decisions(
    store, study, fixture_result, fixture_cards, monkeypatch, tmp_path
):
    import json

    import qpilot.qpcr.study as engine
    from qpilot.core.store import sha256_file

    rdml = tmp_path / "in.rdml"
    rdml.write_bytes(b"stand-in")
    digest = sha256_file(rdml)
    old = fixture_result.model_copy(update={"input_sha256": digest, "study_id": digest[:12]})
    store.put(old, fixture_cards)
    sid = old.study_id
    apply_decision(store, sid, "card_refset", "recommended", "kept", "human")
    (store.workspace(sid) / "format.json").unlink()  # as an older qPilot left it
    new_cards = [
        c.model_copy(update={"impact": {**c.impact, "flips_anywhere": c.id != "card_cutoff"}})
        for c in fixture_cards
    ]
    calls = []
    monkeypatch.setattr(
        engine, "run_study", lambda path: calls.append(path) or (old, new_cards, None)
    )
    assert store.ensure_study(rdml) == sid and len(calls) == 1
    assert store.card(sid, "card_undetermined").impact["flips_anywhere"] is True
    assert store.card(sid, "card_refset").decision == "recommended"  # replayed
    assert json.loads((store.workspace(sid) / "format.json").read_text())["cards"] >= 2
    store.ensure_study(rdml)
    assert len(calls) == 1  # current now: not re-analysed again
