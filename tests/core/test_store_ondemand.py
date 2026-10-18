"""Cards opened on demand (Trace's set-aside cards) and the workspace's artifact files.

An on-demand card lives in ``trace_cards.json`` beside the analysis's ``cards.json``, is decided
through the same path (so the escalation rule governs it), survives a re-analysis, travels in
the Analysis Record, and is checked by ``verify`` like any other card.
"""

import hashlib
import json
import math
import sys
import types
from pathlib import Path

import pytest

from qpilot.core.decisions import apply_decision, reject_request
from qpilot.core.pseudonym import TOKEN
from qpilot.core.record import (
    WORKSPACE_FILES,
    _write_checksums,
    pseudonymise_names,
    rerun_compare,
    unpseudonymised_names,
    verify,
    write_record,
)
from qpilot.core.store import (
    ARTIFACT_FILES,
    ON_DEMAND_FILE,
    PENDING_REASON,
    CardError,
    StudyStore,
    entry_hash,
    sha256_file,
)
from qpilot.mcp_server import QpilotTools
from tests.core.ondemand_helpers import sha, trace_card

CARD = "card_trace_camta2_1"


def _reseal(rec: Path) -> None:
    """What a forger does after editing: rewrite CHECKSUMS.sha256 to match."""
    (rec / "CHECKSUMS.sha256").unlink()
    _write_checksums(rec)


@pytest.fixture
def opened(store, study, fixture_result):
    """The fixture study with one flipping trace card open."""
    store.open_card(study, trace_card(fixture_result))
    return study


# ---- opening ---------------------------------------------------------------------------------


def test_the_hand_built_card_is_realistic(fixture_result):
    card = trace_card(fixture_result)
    assert [o.id for o in card.options] == ["keep", "read_from_other_refs", "set_aside"]
    assert all(len(o.per_gene) == len(fixture_result.contrasts) == 58 for o in card.options)
    assert card.impact["flips"] and card.impact["n_genes_flipped"] == 2
    assert card.evidence["changed_calls"] == ["CAMTA2", "IGSF4"]
    quiet = trace_card(fixture_result, flips=False)
    assert not quiet.impact["flips"] and quiet.impact["n_genes_flipped"] == 0


def test_open_card_keeps_the_card_in_its_own_file(store, study, fixture_result):
    ws = store.workspace(study)
    cards_before, head = sha(ws / "cards.json"), store.chain_head(study)
    opened = store.open_card(study, trace_card(fixture_result))
    assert opened.status == "open" and opened.decision is None
    assert sha(ws / "cards.json") == cards_before
    assert store.chain_head(study) == head  # opening a card writes nothing to the log
    stored = json.loads((ws / ON_DEMAND_FILE).read_text())
    assert [c["id"] for c in stored] == [CARD]
    assert (ws / ON_DEMAND_FILE).read_text().endswith("\n")
    assert [c.id for c in store.cards(study)] == [
        "card_refset",
        "card_cutoff",
        "card_undetermined",
        CARD,
    ]
    assert store.card(study, CARD) == opened
    _, cards, pending = store.snapshot(study)
    assert CARD in {c.id for c in cards} and pending == []


def test_open_card_is_idempotent_and_sorts_by_id(store, study, fixture_result):
    ws = store.workspace(study)
    store.open_card(study, trace_card(fixture_result))
    first = sha(ws / ON_DEMAND_FILE)
    again = store.open_card(study, trace_card(fixture_result))
    assert again == store.card(study, CARD) and sha(ws / ON_DEMAND_FILE) == first
    store.open_card(study, trace_card(fixture_result, "card_trace_camta2_0", sample="1924"))
    ids = [c["id"] for c in json.loads((ws / ON_DEMAND_FILE).read_text())]
    assert ids == ["card_trace_camta2_0", CARD]


def test_reopening_after_an_autonomy_change_returns_the_stored_card(store, opened, fixture_result):
    level = {"autonomy": "decide_and_tell", "effective_autonomy": "suggest"}
    again = store.open_card(opened, trace_card(fixture_result).model_copy(update=level))
    assert again == store.card(opened, CARD) and again.autonomy == "suggest"


def test_reopening_a_decided_card_returns_it_as_decided(store, opened, fixture_result):
    head = store.chain_head(opened)
    apply_decision(store, opened, CARD, "set_aside", "the well read Cq 46", "human", head)
    again = store.open_card(opened, trace_card(fixture_result))
    assert again.status == "decided" and again.decision == "set_aside"


def test_a_card_with_nan_in_it_reopens_as_the_same_card(store, study, fixture_result):
    card = trace_card(fixture_result)
    option = card.options[2]
    nan = option.per_gene["CAMTA2"].model_copy(update={"p": math.nan})
    card.options[2] = option.model_copy(update={"per_gene": {**option.per_gene, "CAMTA2": nan}})
    store.open_card(study, card)
    assert store.open_card(study, card).id == CARD


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"id": "card_refset"}, "card of the analysis"),
        ({"id": "run_review"}, "cannot be a card id"),
        ({"id": ""}, "cannot be a card id"),
        ({"id": " card_x"}, "cannot be a card id"),
        ({"id": "card\nx"}, "cannot be a card id"),
        ({"id": "c" * 129}, "at most 128"),
        ({"kind": "reference_set"}, "built by the analysis"),
        ({"status": "decided"}, "opened undecided"),
        ({"decision": "keep"}, "opened undecided"),
        ({"decided_by": "human"}, "opened undecided"),
        ({"recommended": "drop"}, "recommended option"),
        ({"options": []}, "recommended option"),
        ({"impact": {"n_genes_flipped": 2}}, "flip a conclusion"),
        ({"impact": {"flips": 1}}, "flip a conclusion"),
    ],
)
def test_open_card_refuses_what_it_cannot_govern(store, study, fixture_result, change, match):
    card = trace_card(fixture_result).model_copy(update=change)
    with pytest.raises(CardError, match=match):
        store.open_card(study, card)
    assert not (store.workspace(study) / ON_DEMAND_FILE).exists()


def test_open_card_refuses_duplicate_options(store, study, fixture_result):
    card = trace_card(fixture_result)
    card = card.model_copy(update={"options": [card.options[0], card.options[0]]})
    with pytest.raises(CardError, match="distinct options"):
        store.open_card(study, card)


def test_open_card_refuses_a_different_card_under_an_open_id(store, opened, fixture_result):
    ws = store.workspace(opened)
    before = sha(ws / ON_DEMAND_FILE)
    other = trace_card(fixture_result, sample="1924")
    with pytest.raises(CardError, match="different card"):
        store.open_card(opened, other)
    quiet = trace_card(fixture_result, flips=False)
    with pytest.raises(CardError, match="different card"):
        store.open_card(opened, quiet)  # a card that flips cannot be swapped for one that does not
    assert sha(ws / ON_DEMAND_FILE) == before


def test_open_card_takes_only_a_card(store, study):
    with pytest.raises(CardError, match="DecisionCard"):
        store.open_card(study, {"id": CARD, "kind": "trace_set_aside"})


# ---- deciding --------------------------------------------------------------------------------


def test_a_person_decides_a_trace_card(store, opened, tmp_path):
    ws = store.workspace(opened)
    cards_before = sha(ws / "cards.json")
    head = store.chain_head(opened)
    out = apply_decision(
        store, opened, CARD, "set_aside", "the HMBS well read Cq 46", "human", head
    )
    assert out.status == "applied" and out.card.decision == "set_aside"
    last = store.entries(opened)[-1]
    assert (last.card_id, last.option, last.actor, last.status) == (
        CARD,
        "set_aside",
        "human",
        "applied",
    )
    assert last.prev_hash == head and last.hash == entry_hash(last) == out.chain_head
    assert last.kind is None
    card = store.card(opened, CARD)
    assert (card.status, card.decided_by, card.decided_at) == ("decided", "human", last.at)
    assert sha(ws / "cards.json") == cards_before  # the analysis's cards are not touched
    report = verify(write_record(store, opened, tmp_path / "rec").record_dir)
    assert report.ok, report.summary()
    assert report.n_entries == 2


@pytest.mark.parametrize("autonomy", ["suggest", "decide_and_tell"])
def test_an_agent_never_applies_a_flipping_trace_card(store, opened, autonomy):
    store.set_autonomy(opened, autonomy)
    head = store.chain_head(opened)
    out = apply_decision(store, opened, CARD, "set_aside", "outlier", "agent", head)
    assert out.status == "pending_human" and out.reason == PENDING_REASON
    direct = store.append_decision(opened, CARD, "read_from_other_refs", "try", "agent", None)
    assert direct.status == "pending_human"
    tool = QpilotTools(store).qpcr_decide(opened, CARD, "set_aside", "via MCP")
    assert tool["status"] == "pending_human" and tool["card"]["needs_human"] is True
    card = store.card(opened, CARD)
    assert card.status == "pending_human" and card.decision is None
    assert [(p.card_id, p.option) for p in store.pending(opened)] == [
        (CARD, "set_aside"),
        (CARD, "read_from_other_refs"),
        (CARD, "set_aside"),
    ]
    assert all(e.status != "applied" for e in store.entries(opened) if e.card_id == CARD)


def test_an_agent_may_apply_a_trace_card_that_changes_nothing(store, study, fixture_result):
    store.open_card(study, trace_card(fixture_result, flips=False))
    store.set_autonomy(study, "decide_and_tell")
    out = QpilotTools(store).qpcr_decide(study, CARD, "set_aside", "changes nothing here")
    assert out["status"] == "applied"
    store.set_autonomy(study, "suggest")
    out = QpilotTools(store).qpcr_decide(study, CARD, "keep", "back to keep")
    assert out["status"] == "pending_human"  # Suggest mode: a person confirms


def test_a_person_settles_the_agents_requests(store, opened):
    store.request_human(opened, CARD, "set_aside", "outlier", "agent", None)
    store.request_human(opened, CARD, "read_from_other_refs", "maybe", "agent", None)
    out = reject_request(store, opened, CARD, "the well is fine", None, option="set_aside")
    assert out.status == "rejected"
    assert [p.option for p in store.pending(opened)] == ["read_from_other_refs"]
    apply_decision(store, opened, CARD, "keep", "keep it", "human", store.chain_head(opened))
    assert store.pending(opened) == [] and store.card(opened, CARD).status == "decided"


def test_stale_writes_on_a_trace_card(store, opened):
    head = store.chain_head(opened)
    store.append_decision(opened, CARD, "set_aside", "first", "human", head)
    out = store.append_decision(opened, CARD, "keep", "second", "human", head)
    assert out.status == "stale" and out.card.id == CARD
    assert store.attempts(opened)[-1]["card_id"] == CARD


def test_per_kind_lookups_take_a_trace_card(store, opened, fixture_result, fixture_facts):
    from qpilot.ai import explain
    from qpilot.app_state import card_view
    from qpilot.harness.make_evalset import _safety

    card = store.card(opened, CARD)
    view = card_view(card, fixture_facts)
    assert view.title == "What to do with one unusual well" and view.needs_human
    assert explain.card_view(card)["title"] == view.title
    assert explain.required_facts(card, fixture_facts) == []
    items = _safety(fixture_result, store.cards(opened), 12)
    assert any("the unusual well" in i.question for i in items)
    tools = QpilotTools(store)
    robust = tools.qpcr_robustness(opened, "CAMTA2")
    assert "error" not in robust and CARD in robust["open_cards"]
    assert CARD not in robust["cards_that_can_flip_it"]  # no grid dimension to read it from


def test_the_app_asks_a_person_when_a_card_flips_only_elsewhere(fixture_cards, fixture_facts):
    from qpilot.app_state import card_view

    card = fixture_cards[1].model_copy(
        update={"impact": {**fixture_cards[1].impact, "flips": False, "flips_anywhere": True}}
    )
    assert card_view(card, fixture_facts).needs_human  # the core rule, not flips alone


# ---- surviving a re-analysis, travelling in the record -----------------------------------------


def test_put_again_keeps_trace_cards(store, opened, fixture_result, fixture_cards):
    head = store.chain_head(opened)
    apply_decision(store, opened, CARD, "set_aside", "Cq 46", "human", head)
    ws = store.workspace(opened)
    before = sha(ws / ON_DEMAND_FILE)
    store.put(fixture_result, fixture_cards)
    assert sha(ws / ON_DEMAND_FILE) == before
    assert store.card(opened, CARD).decision == "set_aside"
    assert len(store.entries(opened)) == 2


def test_put_rebuilds_a_trace_card_file_left_behind_by_an_interrupted_write(
    store, opened, fixture_result, fixture_cards
):
    ws = store.workspace(opened)
    stale_copy = (ws / ON_DEMAND_FILE).read_text()
    apply_decision(store, opened, CARD, "set_aside", "Cq 46", "human", store.chain_head(opened))
    (ws / ON_DEMAND_FILE).write_text(stale_copy)  # the log moved on, the file did not
    store.put(fixture_result, fixture_cards)
    assert store.card(opened, CARD).decision == "set_aside"


def test_write_record_copies_trace_cards_and_evidence(store, opened, tmp_path):
    apply_decision(store, opened, CARD, "set_aside", "Cq 46", "human", store.chain_head(opened))
    store.put_artifact(opened, "evidence.json", {"items": [{"id": "E1", "status": "info"}]})
    ws = store.workspace(opened)
    rec = Path(write_record(store, opened, tmp_path / "rec").record_dir)
    for name in (ON_DEMAND_FILE, "evidence.json"):
        assert (rec / name).read_bytes() == (ws / name).read_bytes()
        assert f"  {name}\n" in (rec / "CHECKSUMS.sha256").read_text()
    choices = json.loads((rec / "choices.json").read_text())["cards"]
    assert choices[CARD] == {
        "recommended": "keep",
        "decision": "set_aside",
        "decided_by": "human",
        "status": "decided",
    }
    assert verify(rec).ok


def test_workspace_files_carry_every_artifact():
    assert set(ARTIFACT_FILES) <= set(WORKSPACE_FILES)
    assert ARTIFACT_FILES == (
        "evidence.json",
        "run_context.json",
        "instrument_refs.json",
        "trace_cards.json",
    )


def test_verify_checks_trace_cards_against_the_chain(store, opened, tmp_path):
    apply_decision(store, opened, CARD, "set_aside", "Cq 46", "human", store.chain_head(opened))
    rec = Path(write_record(store, opened, tmp_path / "rec").record_dir)
    cards = json.loads((rec / ON_DEMAND_FILE).read_text())
    cards[0]["decision"] = "keep"
    (rec / ON_DEMAND_FILE).write_text(json.dumps(cards))
    _reseal(rec)
    report = verify(rec)
    assert not report.ok and report.inconsistent == [f"{ON_DEMAND_FILE} {CARD}"]
    assert f"does not match the decision chain: {ON_DEMAND_FILE} {CARD}" in report.summary()


def test_verify_reports_a_decided_trace_card_that_is_gone(store, opened, tmp_path):
    apply_decision(store, opened, CARD, "set_aside", "Cq 46", "human", store.chain_head(opened))
    rec = Path(write_record(store, opened, tmp_path / "rec").record_dir)
    (rec / ON_DEMAND_FILE).write_text("[]\n")
    _reseal(rec)
    assert f"cards.json or {ON_DEMAND_FILE} has no card {CARD}" in verify(rec).inconsistent
    (rec / ON_DEMAND_FILE).unlink()
    _reseal(rec)
    assert f"cards.json has no card {CARD}" in verify(rec).inconsistent


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        (lambda cards: [{**cards[0], "kind": "reference_set"}], "is not an on-demand card"),
        (lambda cards: [{**cards[0], "id": "card_refset"}], "is also in cards.json"),
        (lambda cards: cards + cards, "lists a card twice"),
        (lambda cards: {"not": "a list"}, "unreadable"),
    ],
)
def test_verify_reports_a_malformed_trace_card_file(store, opened, tmp_path, edit, problem):
    rec = Path(write_record(store, opened, tmp_path / "rec").record_dir)
    cards = json.loads((rec / ON_DEMAND_FILE).read_text())
    (rec / ON_DEMAND_FILE).write_text(json.dumps(edit(cards)))
    _reseal(rec)
    report = verify(rec)
    assert not report.ok and any(problem in item for item in report.inconsistent)


# ---- rerun ignores trace cards --------------------------------------------------------------


@pytest.fixture
def study_with_input(store, tmp_path, fixture_result, fixture_cards):
    rdml = tmp_path / "input.rdml"
    rdml.write_bytes(b"<rdml>fake input for on-demand card tests</rdml>")
    digest = sha256_file(rdml)
    result = fixture_result.model_copy(update={"input_sha256": digest, "study_id": digest[:12]})
    store.put(result, fixture_cards)
    store.set_source(result.study_id, rdml)
    return result


def test_rerun_compare_ignores_trace_cards(
    store, study_with_input, fixture_cards, monkeypatch, tmp_path
):
    module = types.ModuleType("qpilot.qpcr.study")
    module.run_study = lambda path, *a, **k: (study_with_input, fixture_cards)
    monkeypatch.setitem(sys.modules, "qpilot.qpcr.study", module)
    sid = study_with_input.study_id
    store.open_card(sid, trace_card(study_with_input))
    apply_decision(store, sid, CARD, "set_aside", "Cq 46", "human", store.chain_head(sid))
    rec = Path(write_record(store, sid, tmp_path / "rec").record_dir)
    assert (rec / ON_DEMAND_FILE).exists() and (rec / "input.rdml").exists()
    report = rerun_compare(rec, tmp_path / "again")
    assert report.same, report.differs
    assert "cards.json (structure)" in report.compared


# ---- artifact files --------------------------------------------------------------------------


def test_put_and_get_artifact(store, study):
    assert store.get_artifact(study, "evidence.json") is None
    data = {"b": [1, 2.5, None], "a": {"ü": "Δ"}}
    path = store.put_artifact(study, "evidence.json", data)
    assert path == store.workspace(study) / "evidence.json"
    assert path.read_text() == json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    assert store.get_artifact(study, "evidence.json") == data
    store.put_artifact(study, "run_context.json", [{"run_id": "r1"}])
    assert store.get_artifact(study, "run_context.json") == [{"run_id": "r1"}]
    assert not [p for p in store.workspace(study).iterdir() if p.name.endswith(".tmp")]


def test_put_artifact_takes_a_mapping(store, study):
    store.put_artifact(study, "instrument_refs.json", types.MappingProxyType({"head": "abc"}))
    assert store.get_artifact(study, "instrument_refs.json") == {"head": "abc"}


@pytest.mark.parametrize(
    ("name", "data", "match"),
    [
        ("notes.json", {}, "not an artifact file"),
        ("../results.json", {}, "not an artifact file"),
        (ON_DEMAND_FILE, [], "open_card only"),
        ("evidence.json", {"x": math.nan}, "plain JSON"),
        ("evidence.json", {"x": math.inf}, "plain JSON"),
        ("evidence.json", {"x": object()}, "plain JSON"),
        ("evidence.json", {1: "x", "a": "y"}, "plain JSON"),
        ("evidence.json", "text", "object or list"),
    ],
)
def test_put_artifact_refuses(store, study, name, data, match):
    with pytest.raises(ValueError, match=match):
        store.put_artifact(study, name, data)
    assert store.get_artifact(study, "evidence.json") is None


def test_get_artifact_refuses_other_files(store, study):
    with pytest.raises(ValueError, match="not an artifact file"):
        store.get_artifact(study, "results.json")


def test_get_artifact_reads_trace_cards(store, opened):
    assert [c["id"] for c in store.get_artifact(opened, ON_DEMAND_FILE)] == [CARD]


# ---- shared records pseudonymise the artifact files -------------------------------------------

RUN_CONTEXT = {
    "source_file": "/Users/jane/runs/HMBS_20080318.eds",
    "run_id": "HMBS_20080318",
    "identity": {"model": "QuantStudio 5", "serial": "272000123", "firmware": "1.3"},
    "run": {"state": "complete", "date_source": "instrument"},
    "well_flags": {"K22": ["NOISE"], "A1": ["PRFDROP"]},
    "aliases": ["QS5 bench 2"],
}
EVIDENCE = {"items": [{"id": "E1", "sample": "2016", "well": "K22", "status": "warn", "n": 3}]}


def _shared(store, sid, tmp_path, fixture_result):
    store.open_card(sid, trace_card(fixture_result))
    store.put_artifact(sid, "run_context.json", RUN_CONTEXT)
    store.put_artifact(sid, "evidence.json", EVIDENCE)
    return Path(write_record(store, sid, tmp_path / "shared", share=True).record_dir)


def test_a_shared_record_pseudonymises_names_in_artifact_files(
    store, study, tmp_path, fixture_result
):
    rec = _shared(store, study, tmp_path, fixture_result)
    token = store.pseudonymiser(study).pseudonymise
    context = json.loads((rec / "run_context.json").read_text())
    assert context["run_id"] == token("HMBS_20080318")
    assert context["source_file"] == token("/Users/jane/runs/HMBS_20080318.eds")
    assert context["identity"] == {
        "model": "QuantStudio 5",
        "serial": token("272000123"),
        "firmware": "1.3",
    }
    assert context["run"] == RUN_CONTEXT["run"]
    assert context["well_flags"] == {token("K22"): ["NOISE"], token("A1"): ["PRFDROP"]}
    assert context["aliases"] == [token("QS5 bench 2")]
    evidence = json.loads((rec / "evidence.json").read_text())
    assert evidence["items"][0] == {
        "id": "E1",
        "sample": token("2016"),
        "well": token("K22"),
        "status": "warn",
        "n": 3,
    }
    card = json.loads((rec / ON_DEMAND_FILE).read_text())[0]
    assert card["id"] == CARD  # in the hash chain: kept as it is
    assert (card["evidence"]["sample"], card["evidence"]["plate"], card["evidence"]["well"]) == (
        token("2016"),
        token("HMBS_20080318"),
        token("K22"),
    )
    assert card["evidence"]["checks"] == ["S1"] and len(card["options"][0]["per_gene"]) == 58
    for name in ("run_context.json", "evidence.json", ON_DEMAND_FILE):
        text = (rec / name).read_text()
        assert "HMBS_20080318" not in text and "272000123" not in text and "jane" not in text
        assert unpseudonymised_names(json.loads(text)) == []
    report = verify(rec)
    assert report.ok, report.summary()


def test_an_unshared_record_keeps_artifact_files_byte_for_byte(
    store, study, tmp_path, fixture_result
):
    store.open_card(study, trace_card(fixture_result))
    store.put_artifact(study, "run_context.json", RUN_CONTEXT)
    rec = Path(write_record(store, study, tmp_path / "plain").record_dir)
    ws = store.workspace(study)
    for name in ("run_context.json", ON_DEMAND_FILE):
        assert (rec / name).read_bytes() == (ws / name).read_bytes()
    assert verify(rec).ok


def test_original_names_in_a_shared_artifact_file_are_reported(
    store, study, tmp_path, fixture_result
):
    rec = _shared(store, study, tmp_path, fixture_result)
    (rec / "run_context.json").write_text(json.dumps(RUN_CONTEXT))
    _reseal(rec)
    report = verify(rec)
    assert not report.ok
    assert report.inconsistent == ["run_context.json holds names in a shared record"]
    assert "inconsistent: run_context.json holds names in a shared record" in report.summary()


def test_an_artifact_file_that_is_not_json_is_reported(store, study, tmp_path):
    store.put_artifact(study, "evidence.json", {"a": 1})
    rec = Path(write_record(store, study, tmp_path / "rec").record_dir)
    (rec / "evidence.json").write_text("{not json")
    _reseal(rec)
    report = verify(rec)
    assert report.inconsistent == ["evidence.json unreadable"]
    assert "inconsistent: evidence.json unreadable" in report.summary()


def test_pseudonymise_names_keeps_tokens_and_everything_else():
    def fake(name):
        return "s_" + hashlib.sha256(name.encode()).hexdigest()[:10]

    already = "s_0123456789"
    data = {"sample": already, "samples": ["a", already], "note": "a", "nested": [{"well": "B2"}]}
    out = pseudonymise_names(data, fake)
    assert out["sample"] == already and out["samples"][1] == already
    assert TOKEN.match(out["samples"][0]) and TOKEN.match(out["nested"][0]["well"])
    assert out["note"] == "a" and data["samples"][0] == "a"  # the input is not changed
    not_text = {"sample": 2016, "well": None}
    assert pseudonymise_names(not_text, fake) == not_text
    assert unpseudonymised_names(data) == ["a", "B2"]


def test_two_names_sharing_a_pseudonym_are_refused():
    from qpilot.core.record import RecordError

    with pytest.raises(RecordError, match="share one pseudonym"):
        pseudonymise_names({"well_flags": {"A1": [], "A2": []}}, lambda name: "s_0000000000")


# ---- demo data -------------------------------------------------------------------------------


@pytest.mark.demo_data
def test_a_trace_card_on_the_demo_study_end_to_end(demo_rdml_path, tmp_studies_dir, tmp_path):
    from qpilot.qpcr.export import study_inputs

    store = StudyStore(tmp_studies_dir)
    sid = store.ensure_study(demo_rdml_path)
    result = store.get(sid)
    engine_ids = [c.id for c in store.cards(sid)]
    card = store.open_card(sid, trace_card(result))
    assert len(card.options[0].per_gene) == len(result.contrasts) == 58
    out = QpilotTools(store).qpcr_decide(sid, CARD, "set_aside", "the agent asks")
    assert out["status"] == "pending_human"
    head = store.chain_head(sid)
    out = apply_decision(store, sid, CARD, "set_aside", "the HMBS well read Cq 46", "human", head)
    assert out.status == "applied"
    inputs = study_inputs(store, sid, read_only=True)
    assert [c.card_id for c in inputs.choices] == engine_ids  # the trace card is no choice
    assert inputs.chain_head == store.chain_head(sid)
    rec = Path(write_record(store, sid, tmp_path / "rec").record_dir)
    report = verify(rec)
    assert report.ok, report.summary()
    rerun = rerun_compare(rec, tmp_path / "again")
    assert rerun.same, rerun.differs
