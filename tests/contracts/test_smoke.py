"""Contract smoke test: cards and facts fixtures validate against the frozen schemas."""


def test_cards_and_facts_load(fixture_cards, fixture_facts):
    assert [c.id for c in fixture_cards] == ["card_refset", "card_cutoff", "card_undetermined"]
    assert [c.impact["n_genes_flipped"] for c in fixture_cards] == [31, 17, 0]
    assert fixture_cards[2].status == "auto_decided"
    for card in fixture_cards:
        missing = [fid for fid in card.facts if fid not in fixture_facts]
        assert not missing, f"{card.id} references unknown facts: {missing[:5]}"
