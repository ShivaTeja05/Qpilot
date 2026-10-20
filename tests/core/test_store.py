import json

import pytest

from qpilot.core import robustness as rb
from qpilot.core.store import StudyNotFound, StudyStore, entry_hash, read_entries, sha256_file
from tests.core.toy_space import ToySpace


def test_put_get_round_trip(store, study, fixture_result, fixture_cards):
    assert store.get(study) == fixture_result
    cards = store.cards(study)
    assert [c.id for c in cards] == [c.id for c in fixture_cards]
    assert store.list_studies() == [study]
    ws = store.workspace(study)
    assert ws.name == fixture_result.input_sha256
    assert json.loads((ws / "facts.json").read_text()) == {
        k: v.model_dump(mode="json") for k, v in fixture_result.facts.items()
    }


def test_no_temp_files_left(store, study):
    ws = store.workspace(study)
    assert not [p for p in ws.iterdir() if p.name.endswith(".tmp")]


def test_chain_starts_at_input_hash(store, study, fixture_result):
    first = store.entries(study)[0]
    assert first.prev_hash == fixture_result.input_sha256
    assert first.hash == entry_hash(first)


def test_put_writes_grid(store, fixture_result, fixture_cards):
    space = ToySpace()
    store.put(fixture_result, fixture_cards, rb.run_grid(space))
    text = (store.workspace(fixture_result.study_id) / "grid.csv").read_text()
    assert text.splitlines()[0].startswith("a,b,a__idx,b__idx,item")
    assert len(text.splitlines()) == 1 + 18


def test_put_again_keeps_decisions(store, study, fixture_result, fixture_cards):
    store.append_decision(study, "card_refset", "top2", "two most stable", "human", None)
    store.put(fixture_result, fixture_cards)
    assert store.card(study, "card_refset").decision == "top2"
    assert len(store.entries(study)) == 2  # no second system entry


def test_study_id_is_checked(store, study):
    for bad in ["../etc", "", "ZZZ", "bc1d/../", None, 123]:
        with pytest.raises(StudyNotFound):
            store.workspace(bad)
    with pytest.raises(StudyNotFound):
        store.get("abcdef123456")


def test_default_dir_from_env(tmp_studies_dir):
    assert StudyStore().root == tmp_studies_dir


def test_read_entries_missing_file(tmp_path):
    assert read_entries(tmp_path / "nope.jsonl") == []


def test_sha256_file(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    assert sha256_file(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_ensure_study_uses_existing_workspace(store, tmp_path, fixture_result, fixture_cards):
    rdml = tmp_path / "in.rdml"
    rdml.write_bytes(b"<rdml/>")
    digest = sha256_file(rdml)
    result = fixture_result.model_copy(update={"input_sha256": digest, "study_id": digest[:12]})
    store.put(result, fixture_cards)
    assert store.ensure_study(rdml) == digest[:12]


def test_two_auto_decided_cards_make_an_unbroken_chain(store, fixture_result, fixture_cards):
    # Regression: put() appended each auto entry twice to its in-memory list, so the second
    # auto entry was written with seq 3 and `qpilot verify` reported the chain broken.
    from qpilot.core.record import verify_chain

    autos = [
        c.model_copy(
            update={"status": "auto_decided", "decision": c.recommended, "reason": "no conclusion"}
        )
        for c in fixture_cards[:2]
    ]
    store.put(fixture_result, autos + fixture_cards[2:])
    entries = store.entries(fixture_result.study_id)
    assert len(entries) >= 2
    assert [e.seq for e in entries] == list(range(1, len(entries) + 1))
    assert verify_chain(entries, fixture_result.input_sha256) is None
