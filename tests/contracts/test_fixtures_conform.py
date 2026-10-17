"""The T0 fixtures are the contract: they must validate against qpilot.schemas."""

import json

from qpilot.schemas import DecisionCard, Fact, StudyResult


def test_results_validate(fixture_result: StudyResult):
    assert fixture_result.n_plates == 64
    assert fixture_result.n_reactions == 24576
    assert set(fixture_result.robustness) == set(fixture_result.contrasts)


def test_cards_validate(fixture_cards: list[DecisionCard]):
    assert [c.id for c in fixture_cards] == ["card_refset", "card_cutoff", "card_undetermined"]
    for card in fixture_cards:
        assert card.recommended in {o.id for o in card.options}


def test_facts_validate(fixture_facts: dict[str, Fact]):
    for fid, fact in fixture_facts.items():
        assert fact.id == fid
        assert fid == fid.lower() and fid.startswith("f_")


def test_card_fact_ids_exist(fixture_cards: list[DecisionCard], fixture_facts: dict[str, Fact]):
    for card in fixture_cards:
        missing = [fid for fid in card.facts if fid not in fixture_facts]
        assert not missing, (card.id, missing)


def test_result_facts_match_facts_file(fixture_result: StudyResult, fixture_facts):
    assert fixture_result.facts == fixture_facts


def test_confidence_fact_ids_exist(fixture_result: StudyResult, fixture_facts):
    for gene, grade in fixture_result.confidence.items():
        for check in grade.checks:
            missing = [fid for fid in check.fact_ids if fid not in fixture_facts]
            assert not missing, (gene, check.id, missing)


def test_ranks_are_dense_and_ordered(fixture_cards: list[DecisionCard]):
    ranks = [c.rank for c in fixture_cards]
    assert sorted(ranks) == list(range(1, len(ranks) + 1))
    by_rank = sorted(fixture_cards, key=lambda c: c.rank)
    flipped = [c.impact["n_genes_flipped"] for c in by_rank]
    assert flipped == sorted(flipped, reverse=True)


def test_auto_decided_cards_flip_nothing(fixture_cards: list[DecisionCard]):
    for card in fixture_cards:
        if card.status == "auto_decided":
            assert card.impact["n_genes_flipped"] == 0
            assert card.impact["flips"] is False


def test_fixture_json_round_trips(fixtures_dir):
    raw = json.loads((fixtures_dir / "results.json").read_text())
    again = json.loads(StudyResult.model_validate(raw).model_dump_json())
    assert again["contrasts"]["ODC1"]["fc"] == raw["contrasts"]["ODC1"]["fc"]
