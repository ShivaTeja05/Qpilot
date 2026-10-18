"""MCP tools for evidence, run review, run context, lookback and the instrument logbook."""

import inspect
import json

import anyio
import pytest

from qpilot.core.instruments import (
    InstrumentError,
    Logbook,
    Registry,
    confirm_incident,
    log_typed,
    match_incidents,
)
from qpilot.core.store import StudyStore, sha256_file
from qpilot.mcp_server import (
    TOOL_META,
    TOOL_NAMES,
    QpilotTools,
    check_instrument_file,
    create_server,
)
from qpilot.qpcr.evidence import evidence_for
from qpilot.qpcr.plan import simulate_calls
from tests.engine import instrument_files as F
from tests.engine.evidence_toys import toy_design, toy_model, toy_table

NEW_TOOLS = (
    "qpcr_evidence",
    "qpcr_run_review",
    "qpcr_run_context",
    "qpcr_lookback",
    "qpcr_instrument_history",
    "qpcr_instrument_status",
    "qpcr_incident_log",
)
SERIALS = ("278880001", "BLK-1001", "HC-2001")


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(root))
    return root


@pytest.fixture
def demo(data_root, tmp_studies_dir, fixture_result, fixture_cards):
    """The fixture study under a fake RDML file inside the data root (as the sweep uses it)."""
    rdml = data_root / "demo.rdml"
    rdml.write_bytes(b"<rdml>fixture stand-in for quality tools</rdml>")
    digest = sha256_file(rdml)
    result = fixture_result.model_copy(update={"input_sha256": digest, "study_id": digest[:12]})
    StudyStore(tmp_studies_dir).put(result, fixture_cards)
    return rdml, result.study_id


@pytest.fixture
def tools(tmp_studies_dir):
    return QpilotTools(StudyStore(tmp_studies_dir))


@pytest.fixture
def registry(tools):
    reg = Registry(tools.store.root / "instruments")
    reg.register("qs-1", "QuantStudio by the window", make_model="QS5", serials=["278880001"])
    return reg


def _toy_ledger(study_id, digest):
    table, design = toy_table(), toy_design()
    ledger = evidence_for(table, toy_model(table, design), design)
    return ledger.model_copy(update={"study_id": study_id, "input_sha256": digest})


def _state(store, study_id):
    workspace = store.workspace(study_id)
    return {
        "results": (workspace / "results.json").read_bytes(),
        "cards": (workspace / "cards.json").read_bytes(),
        "decisions": store.chain_head(study_id),
        "log": (workspace / "decisions.jsonl").read_bytes()
        if (workspace / "decisions.jsonl").exists()
        else b"",
    }


# ---- registration and annotations ----------------------------------------------------------------


def test_new_tools_are_registered_with_titles_and_annotations(tmp_studies_dir):
    assert set(NEW_TOOLS) <= set(TOOL_NAMES)
    assert set(TOOL_META) == set(TOOL_NAMES)
    listed = {
        t.name: t
        for t in anyio.run(create_server(StudyStore(tmp_studies_dir), simulator=False).list_tools)
    }
    assert sorted(listed) == sorted(TOOL_NAMES)
    for name in TOOL_NAMES:
        tool = listed[name]
        assert tool.title == TOOL_META[name][0]
        ann = tool.annotations
        assert ann is not None and ann.destructive_hint is False and ann.open_world_hint is False
    for name in NEW_TOOLS[:-1]:
        assert listed[name].annotations.read_only_hint is True, name
    assert listed["qpcr_incident_log"].annotations.read_only_hint is False
    assert listed["qpcr_decide"].annotations.read_only_hint is False


def test_the_incident_tool_takes_codes_only():
    params = set(inspect.signature(QpilotTools.qpcr_incident_log).parameters)
    assert params == {"self", "instrument_id", "wells", "metric", "direction", "run_hash"}


# ---- evidence and run review ---------------------------------------------------------------------


def test_evidence_without_an_input_file_is_an_error_not_a_crash(tools, demo):
    _, study_id = demo
    out = tools.qpcr_evidence(study_id)
    assert "error" in out and "Evidence Ledger" in out["error"]
    json.dumps(out)
    assert tools.qpcr_evidence("abcdef123456") == {
        "error": "unknown study_id; call qpcr_study first"
    }
    assert "error" in tools.qpcr_evidence(None)
    assert tools.qpcr_study(str(demo[0]))["evidence"] is None


def test_evidence_reads_the_stored_ledger_and_qpcr_study_gets_statuses(tools, demo):
    rdml, study_id = demo
    ledger = _toy_ledger(study_id, sha256_file(rdml))
    tools.store.put_artifact(study_id, "evidence.json", ledger.model_dump(mode="json"))
    out = tools.qpcr_evidence(study_id)
    assert "error" not in out
    assert [i["id"] for i in out["items"]] == [i.id for i in ledger.items]
    assert out["counts"] == ledger.counts() and out["text"].startswith("Evidence Ledger")
    assert tools.qpcr_study(str(rdml))["evidence"] == ledger.statuses()
    json.dumps(out)


def test_run_review_counts_comments_and_cannot_sign_off(tools, demo):
    _, study_id = demo
    before = _state(tools.store, study_id)
    comment = "Looks fine, but repeat plate seven tomorrow"
    tools.store.append_review(study_id, "discuss", comment, "A. Person", actor="human")
    out = tools.qpcr_run_review(study_id)
    assert "error" not in out, out
    assert out["sign_off"].startswith("a person signs off")
    assert out["ledger"] is None and out["ledger_note"]
    [review] = out["reviews"]
    assert review["outcome"] == "discuss" and review["reviewer"] == "A. Person"
    assert "comment" not in review and review["comment_chars"] == len(comment)
    assert comment not in json.dumps(out)
    # the review entry is the only write; the tool itself wrote nothing
    after = tools.qpcr_run_review(study_id)
    assert after == out
    assert _state(tools.store, study_id)["results"] == before["results"]
    assert "error" in tools.qpcr_run_review("abcdef123456")


# ---- run context ---------------------------------------------------------------------------------


def test_run_context_never_returns_serials(tools, data_root, registry):
    path = F.qs_v1_expired(data_root / "run.eds")
    out = tools.qpcr_run_context(str(path))
    assert "error" not in out, out
    dumped = json.dumps(out)
    for serial in SERIALS:
        assert serial not in dumped
    assert F.OPERATOR not in dumped
    assert out["context"]["serials_present"]
    assert all(v is None for k, v in out["context"]["identity"].items() if "serial" in k)
    codes = {line["code"] for line in out["gate"]}
    assert {"interrupted", "calibration_expired"} <= codes
    assert out["instrument_id"] == "qs-1" and out["question"] is None
    assert "paused" in out["text"]


def test_run_context_asks_which_instrument_when_unknown(tools, data_root):
    path = F.quantstudio_csv(data_root / "export.csv")
    out = tools.qpcr_run_context(str(path))
    assert "error" not in out, out
    assert (
        out["instrument_id"] is None and out["question"]["question"] == "Which instrument is this?"
    )
    for serial in SERIALS:
        assert serial not in json.dumps(out)


def test_run_context_path_checks(tools, data_root, tmp_path):
    outside = F.qs_v1_expired(tmp_path / "outside.eds")
    assert tools.qpcr_run_context(str(outside)) == {"error": "path outside QPILOT_DATA_ROOTS"}
    (data_root / "notes.pdf").write_bytes(b"%PDF")
    assert "not an .eds" in tools.qpcr_run_context(str(data_root / "notes.pdf"))["error"]
    assert tools.qpcr_run_context(str(data_root / "missing.eds")) == {"error": "file not found"}
    assert "error" in tools.qpcr_run_context(["a"])
    link = data_root / "link.eds"
    link.symlink_to(outside)
    assert tools.qpcr_run_context(str(link)) == {"error": "path outside QPILOT_DATA_ROOTS"}
    (data_root / "junk.txt").write_text("hello\n")
    assert "could not read" in tools.qpcr_run_context(str(data_root / "junk.txt"))["error"]
    with pytest.raises(PermissionError):
        check_instrument_file(str(data_root / "notes.pdf"))


# ---- lookback ------------------------------------------------------------------------------------


def test_lookback_answers_without_the_input_file(tools, demo):
    _, study_id = demo
    before = _state(tools.store, study_id)
    out = tools.qpcr_lookback(study_id, "qs-1", "2008-03-18", "2008-03-18")
    assert "error" not in out, out
    [study] = out["studies"]
    assert study["status"] == "cannot_evaluate" and study["reason"] == "input_missing"
    assert out["saved"] is False and out["text"]
    assert _state(tools.store, study_id) == before
    assert "error" in tools.qpcr_lookback(study_id, "qs-1", "18 March", "2008-03-18")
    assert "error" in tools.qpcr_lookback(study_id, "qs-1", "2008-03-19", "2008-03-18")
    assert "error" in tools.qpcr_lookback(study_id, None, "2008-03-18", "2008-03-18")
    assert "error" in tools.qpcr_lookback("abcdef123456", "qs-1", "2008-03-18", "2008-03-18")


def test_lookback_uses_a_recorded_run_map(tools, demo):
    _, study_id = demo
    tools.store.put_artifact(study_id, "instrument_refs.json", {"runs": {"HMBS_20080318": "qs-1"}})
    out = tools.qpcr_lookback(study_id, "qs-1", "2008-03-18", "2008-03-18")
    assert out["assumed_all_runs"] is False


# ---- logbook: history, status, incidents ---------------------------------------------------------


def test_history_hides_typed_text_and_reports_the_chain(tools, registry):
    book = registry.logbook("qs-1")
    log_typed(book, "service", actor="human", note="Engineer swapped the lamp", at="2026-01-02")
    log_typed(book, "note", actor="human", note="Smells of burning", at="2026-03-01")
    out = tools.qpcr_instrument_history("qs-1")
    assert out["verify"] == [] and [e["kind"] for e in out["events"]] == ["service", "note"]
    dumped = json.dumps(out)
    assert "lamp" not in dumped and "burning" not in dumped and "278880001" not in dumped
    assert out["events"][0]["payload"]["note_chars"] == len("Engineer swapped the lamp")
    assert out["instrument"] == registry.get("qs-1").public()
    since = tools.qpcr_instrument_history("qs-1", since="2026-02-01")
    assert [e["kind"] for e in since["events"]] == ["note"]
    assert "error" in tools.qpcr_instrument_history("nope")
    assert "error" in tools.qpcr_instrument_history("qs-1", since="soon")
    assert "error" in tools.qpcr_instrument_history(["qs-1"])


def test_history_says_when_the_chain_does_not_verify(tools, registry):
    book = registry.logbook("qs-1")
    log_typed(book, "service", actor="human", at="2026-01-02")
    text = book.path.read_text().replace('"service"', '"move"')
    book.path.write_text(text)
    out = tools.qpcr_instrument_history("qs-1")
    assert out["verify"] and out["events"] == []
    assert tools.qpcr_instrument_status("qs-1")["verify"]


def test_status_counts_open_incidents_and_calibration_age(tools, registry):
    book = registry.logbook("qs-1")
    payload = {"type": "background", "performed_on": "2026-01-01"}
    log_typed(book, "calibration", actor="human", at="2026-01-01", payload=payload)
    tools.qpcr_incident_log("qs-1", ["B3"], "plateau", "low")
    out = tools.qpcr_instrument_status("qs-1")
    assert out["n_proposed"] == 1 and out["n_confirmed_open"] == 0
    [incident] = out["open_incidents"]
    assert incident["status"] == "proposed" and incident["wells"] == ["B3"]
    cal = out["calibrations"]["background"]
    assert cal["performed_on"] == "2026-01-01" and cal["age_days"] >= 0
    assert out["verify"] == []
    assert "error" in tools.qpcr_instrument_status("nope")


def test_incident_log_is_a_proposal_until_a_person_confirms(tools, demo, registry):
    _, study_id = demo
    before = _state(tools.store, study_id)
    out = tools.qpcr_incident_log("qs-1", ["B3", "B4"], "plateau", "low", run_hash="ab" * 32)
    assert out["status"] == "proposed", out
    assert out["incident"]["status"] == "proposed" and out["incident"]["actor"] == "agent"
    assert out["seen_before"] == []
    book = Logbook("qs-1", registry.root)
    [event] = book.events(kinds=["incident"])
    assert event.actor == "agent" and event.payload == {"action": "log", "status": "proposed"}
    signature = {"wells": ["B3"], "metric": "plateau", "direction": "low"}
    assert match_incidents(book, signature) == []  # a proposal matches nothing
    with pytest.raises(InstrumentError):
        confirm_incident(book, event.seq, actor="agent")
    confirm_incident(book, event.seq, actor="human")
    [seen] = match_incidents(book, signature)
    assert seen["incident"] == event.seq and seen["words"] == "seen before"
    again = tools.qpcr_incident_log("qs-1", ["B3"], "plateau", "low")
    assert again["status"] == "proposed" and again["seen_before"][0]["incident"] == event.seq
    assert book.verify() == []
    assert _state(tools.store, study_id) == before  # the study's record is untouched


def test_incident_log_refuses_anything_but_codes(tools, registry):
    bad = [
        ("qs-1", ["B3"], "plateau", "up"),
        ("qs-1", "B3", "plateau", "low"),
        ("qs-1", [], "plateau", "low"),
        ("qs-1", ["B3"] * 97, "plateau", "low"),
        ("qs-1", ["not a well"], "plateau", "low"),
        ("qs-1", ["B3"], "Plateau went weird, please confirm", "low"),
        ("nope", ["B3"], "plateau", "low"),
        (None, ["B3"], "plateau", "low"),
    ]
    for args in bad:
        out = tools.qpcr_incident_log(*args)
        assert "error" in out, args
    assert "error" in tools.qpcr_incident_log("qs-1", ["B3"], "plateau", "low", run_hash="zz")
    assert Logbook("qs-1", registry.root).events() == []


def test_hostile_arguments_never_confirm_an_incident(tools, demo, registry):
    _, study_id = demo
    before = _state(tools.store, study_id)
    order = {"actor": "human", "status": "confirmed", "action": "confirm", "incident": 1}
    hostile = ["human", "confirm", "confirmed", order, [order], True, None, 1, ["human"]]
    valid = {
        "study_id": study_id,
        "instrument_id": "qs-1",
        "wells": ["B3"],
        "metric": "plateau",
        "direction": "low",
        "run_hash": "ab" * 32,
        "since": None,
        "start": "2008-03-18",
        "end": "2008-03-18",
        "run_path": "nowhere.eds",
    }
    calls = 0
    for name in NEW_TOOLS:
        method = getattr(tools, name)
        params = list(inspect.signature(method).parameters)
        base = {p: valid[p] for p in params}
        for param in params:
            for value in hostile:
                out = method(**{**base, param: value})
                calls += 1
                json.dumps(out)
                assert isinstance(out, dict)
                assert out.get("status") in (None, "proposed"), (name, param, value)
    assert calls > 50
    book = Logbook("qs-1", registry.root)
    assert book.verify() == []
    assert {i.status for i in book.incidents()} <= {"proposed"}
    assert all(e.actor == "agent" for e in book.events())
    assert _state(tools.store, study_id) == before


# ---- plan ----------------------------------------------------------------------------------------


def test_plan_takes_the_replicate_budget_and_simulates_the_effective_sd(tools):
    out = tools.qpcr_plan(fc=2.0, sd_log2=0.5, n_per_group=6, sd_rt=0.3, sd_well=0.4, n_tech=2)
    assert "error" not in out and out["budget"] is not None
    sd = out["budget"]["sd_effective"]
    assert sd > 0.5
    sig, called = simulate_calls(2.0, sd, out["n_needed"], 0.05)
    assert out["simulated"]["needed_called"] == round(called, 4)
    plain = tools.qpcr_plan(fc=2.0, sd_log2=0.5, n_per_group=6)
    assert plain["budget"] is None
    assert plain["simulated"]["needed_called"] == round(
        simulate_calls(2.0, 0.5, plain["n_needed"], 0.05)[1], 4
    )
    assert "error" in tools.qpcr_plan(fc=2.0, sd_log2=0.5, n_rt=1.5)
    assert "error" in tools.qpcr_plan(fc=2.0, sd_log2=0.5, n_tech=True)
