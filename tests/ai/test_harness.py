import json

from qpilot.ai.client import MockBackend, ModelClient
from qpilot.harness.make_evalset import KINDS, build_items
from qpilot.harness.report import markdown, write
from qpilot.harness.run import run


def test_evalset_has_thirty_items_of_three_kinds(fixture_result, fixture_cards, fixture_facts):
    items = build_items(fixture_result, fixture_cards, fixture_facts)
    assert len(items) == 30
    assert {i.kind for i in items} == set(KINDS)
    assert len({i.id for i in items}) == 30
    assert build_items(fixture_result, fixture_cards) == items  # deterministic
    safety = [i for i in items if i.kind == "decision_safety"]
    assert all(i.expected["status"] == "pending_human" for i in safety)
    refusal = [i for i in items if i.kind == "refusal"]
    assert all(i.expected["gene"] not in fixture_result.contrasts for i in refusal)


def test_none_profile_scores_safe_and_honest(store, study, fixture_result, fixture_cards):
    items = build_items(fixture_result, fixture_cards)
    report = run(items, ModelClient(), store, study, profile_name="none")
    assert report.safety == [10, 10]
    assert report.invented_numbers == 0
    assert report.correct_by_kind["lookup"] == [10, 10]
    assert report.correct_by_kind["refusal"] == [10, 10]
    assert report.correct == 30
    # the real study was not touched by the decision-safety items
    assert store.pending(study) == []
    assert store.card(study, "card_refset").decision is None


def test_bad_model_is_caught(store, study, fixture_result, fixture_cards):
    items = build_items(fixture_result, fixture_cards)
    client = ModelClient(MockBackend(["42"]))
    report = run(items, client, store, study, profile_name="always-42")
    assert report.invented_numbers > 0
    assert report.fallbacks > 0
    assert report.correct_by_model < report.correct  # the templates did the work
    assert report.safety == [10, 10]  # the gate holds in code whatever the model says


def test_good_mock_model(store, study, fixture_result, fixture_cards):
    def reply(system, messages):
        content = messages[0]["content"]
        if "Choose exactly one tool" in system:
            data = json.loads(content)
            q = data["question"]
            gene = next((g for g in data["genes_in_study"] if g in q), None)
            if q.startswith("Apply"):
                card = data["cards"][0]
                option = next(
                    (o for o in card["options"] if o.replace("_", " ") in q.lower()), None
                )
                if option is None:
                    return json.dumps({"tool": "none", "args": {}})
                return json.dumps(
                    {"tool": "qpcr_decide", "args": {"card_id": card["card_id"], "option": option}}
                )
            if gene:
                return json.dumps({"tool": "qpcr_robustness", "args": {"gene": gene}})
            return json.dumps({"tool": "none", "args": {}})
        data = json.loads(content)
        if data["result"].get("status") == "pending_human":
            return "Not applied; a human must decide this choice."
        if "error" in data["result"]:
            return "That gene is not in this study."
        if "share" in data["question"]:
            return "It holds in {{f_ans_holds}} of analyses."
        return "The fold change is {{f_ans_fc}}."

    items = build_items(fixture_result, fixture_cards)
    report = run(items, ModelClient(MockBackend(reply)), store, study, profile_name="mock")
    assert report.invented_numbers == 0 and report.fallbacks == 0
    assert report.correct_by_kind["lookup"] == [10, 10]
    assert report.correct_by_model == report.correct
    assert report.safety[0] >= 1  # top-two/HMBS-alone style options route to decide


def test_report_files(store, study, fixture_result, fixture_cards, tmp_path):
    items = build_items(fixture_result, fixture_cards, n_per_type=2)
    report = run(items, ModelClient(), store, study, profile_name="none")
    json_path, md_path = write(report, tmp_path)
    assert json.loads(json_path.read_text())["correct"] == report.correct
    table = markdown([report])
    assert "| none | 6/6 | — | 0 | 2/2 | — |" in table
    assert md_path.read_text() == table
    store.put_scorecard(study, {"none": report.model_dump()})
    assert store.scorecard(study)["none"]["n_items"] == 6
